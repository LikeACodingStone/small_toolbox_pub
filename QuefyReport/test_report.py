from datetime import datetime
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from report import TEMPLATE, generate, select_days

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def event(kind, day, clock):
    return {'kind': kind, 'timestamp': f'2026-10-{day:02d}T{clock}'}


class ReportTests(unittest.TestCase):
    def test_today_departure_is_blank_until_next_day(self):
        events = [event('startup', 13, '08:00:00'), event('shutdown', 13, '18:00:00')]
        today = select_days(events, datetime(2026, 10, 13, 20))
        self.assertIn('startup', today[13])
        self.assertNotIn('shutdown', today[13])
        tomorrow = select_days(events, datetime(2026, 10, 14, 9))
        self.assertEqual(tomorrow[13]['shutdown'].hour, 18)
        self.assertEqual(select_days(events[1:], datetime(2026, 10, 13, 20)), {})

    def test_thresholds_and_cutoff(self):
        events = [event('startup', 1, t) for t in ['06:00:00', '06:59:59', '08:00:00', '07:00:00']]
        events += [event('shutdown', 1, t) for t in ['23:30:01', '23:59:00', '23:30:00', '18:00:00']]
        events += [event('startup', 14, '09:00:00'), event('shutdown', 13, '20:00:00')]
        days = select_days(events, datetime(2026, 10, 13, 12))
        self.assertEqual(set(days), {1})
        self.assertEqual(days[1]['startup'].hour, 7)
        self.assertEqual(days[1]['shutdown'].strftime('%H:%M'), '23:30')

    def test_weekends_missing_and_reversed(self):
        events = [event('startup', 3, '09:00:00'), event('shutdown', 3, '01:00:00'),
                  event('shutdown', 4, '18:00:00'), event('startup', 5, '06:00:00')]
        days = select_days(events, datetime(2026, 10, 13))
        self.assertEqual(set(days), {3, 4})
        self.assertNotIn('shutdown', days[3])
        self.assertNotIn('startup', days[4])

    def test_template_preservation_and_months(self):
        original = TEMPLATE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            for year, month, count in [(2026, 10, 31), (2026, 11, 30), (2027, 2, 28), (2028, 2, 29)]:
                output = Path(directory) / f'{year}-{month}.xlsx'
                events = [{'kind': 'startup', 'timestamp': f'{year}-{month:02d}-03T08:45:00'}]
                generate(TEMPLATE, output, events, datetime(year, month, 13))
                with ZipFile(TEMPLATE) as src, ZipFile(output) as dst:
                    self.assertEqual(src.namelist(), dst.namelist())
                    for name in src.namelist():
                        if name not in ('xl/workbook.xml', 'xl/worksheets/sheet1.xml'):
                            self.assertEqual(src.read(name), dst.read(name), name)
                    old = ET.fromstring(src.read('xl/worksheets/sheet1.xml'))
                    new = ET.fromstring(dst.read('xl/worksheets/sheet1.xml'))
                    old_formulas = [ET.tostring(f) for f in old.findall('.//s:f', NS)]
                    self.assertEqual(old_formulas, [ET.tostring(f) for f in new.findall('.//s:f', NS)])
                    cells = {c.get('r'): c for c in new.findall('.//s:c', NS)}
                    self.assertEqual(cells['AB2'].find('s:v', NS).text, str(month))
                    self.assertEqual(cells['I49'].find('s:v', NS).text, str(count))
                    self.assertEqual(cells['E20'].find('s:is/s:t', NS).text, '出勤（Bosch）')
                    self.assertEqual(cells['J20'].find('s:v', NS).text, '45')
                    for ref in ('E18', 'K20', 'E31', 'I48'):
                        self.assertEqual(len(cells[ref]), 0, ref)
                with self.assertRaises(FileExistsError):
                    generate(TEMPLATE, output, [], datetime(year, month, 13))
            with self.assertRaises(ValueError):
                generate(TEMPLATE, TEMPLATE, [], datetime(2026, 10, 13))
        self.assertEqual(original, TEMPLATE.read_bytes())


if __name__ == '__main__':
    unittest.main()
