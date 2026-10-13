"""Generate the current month's Quefy report without rewriting template assets."""
import argparse
import calendar
from datetime import datetime, time
import json
from pathlib import Path
import re
import subprocess
import sys
from xml.sax.saxutils import escape
from zipfile import ZipFile

TEMPLATE = Path(__file__).resolve().parent.parent / 'Quefy株式会社2026年9月作業報告書(周尚軍).xlsx'
CELL = re.compile(r'<c\b[^>]*?(?:/>|>.*?</c>)', re.DOTALL)


def windows_events(now):
    """Provider-qualified System events; no localized text parsing or 6008 timestamps."""
    if sys.platform != 'win32':
        raise RuntimeError('自动读取需要在工作的 Windows 电脑上运行；其他系统可使用 --events JSON文件。')
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    script = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$start = [datetime]::Parse('__START__', [cultureinfo]::InvariantCulture)
$end = [datetime]::Parse('__END__', [cultureinfo]::InvariantCulture)
try {
    $events = @(Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=$start; EndTime=$end; Id=1,12,13,42} -ErrorAction Stop)
} catch {
    if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { $events = @() } else { throw }
}
$result = @(foreach ($e in $events) {
    $kind = $null
    if (($e.ProviderName -eq 'Microsoft-Windows-Kernel-General' -and $e.Id -eq 12) -or
        ($e.ProviderName -eq 'Microsoft-Windows-Power-Troubleshooter' -and $e.Id -eq 1)) { $kind = 'startup' }
    if (($e.ProviderName -eq 'Microsoft-Windows-Kernel-General' -and $e.Id -eq 13) -or
        ($e.ProviderName -eq 'Microsoft-Windows-Kernel-Power' -and $e.Id -eq 42)) { $kind = 'shutdown' }
    if ($kind) {
        $stamp = $e.TimeCreated
        if ($e.ProviderName -eq 'Microsoft-Windows-Power-Troubleshooter') {
            $xml = [xml]$e.ToXml()
            $wake = $xml.Event.EventData.Data | Where-Object { $_.Name -eq 'WakeTime' }
            if ($wake) { $stamp = [datetimeoffset]::Parse($wake.InnerText).LocalDateTime }
        }
        @{kind=$kind; timestamp=$stamp.ToString('yyyy-MM-ddTHH:mm:ss')}
    }
})
ConvertTo-Json -InputObject $result -Compress
'''.replace('__START__', start.isoformat()).replace('__END__', now.isoformat())
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, encoding='utf-8', check=False)
    if result.returncode:
        raise RuntimeError('Windows事件日志读取失败：' + result.stderr.strip())
    return json.loads(result.stdout.lstrip('\ufeff'))


def select_days(events, now):
    days = {}
    for event in events:
        stamp = datetime.fromisoformat(event['timestamp'])
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone().replace(tzinfo=None)
        kind = event['kind']
        if kind not in ('startup', 'shutdown'):
            raise ValueError('未知事件类型：' + kind)
        if (stamp.year, stamp.month) != (now.year, now.month) or stamp > now:
            continue
        if kind == 'startup' and stamp.time() < time(7):
            continue
        if kind == 'shutdown' and (stamp.date() == now.date() or stamp.time() > time(23, 30)):
            continue
        day = days.setdefault(stamp.day, {})
        previous = day.get(kind)
        if previous is None or (kind == 'startup' and stamp < previous) or (kind == 'shutdown' and stamp > previous):
            day[kind] = stamp
    # An overnight/earlier shutdown must not produce negative hours for today's start.
    for day in days.values():
        if 'startup' in day and 'shutdown' in day and day['shutdown'] < day['startup']:
            del day['shutdown']
    return days


def patch_sheet(xml, values):
    found = set()
    def replace(match):
        cell = match.group()
        ref = re.search(r'\br="([A-Z]+[0-9]+)"', cell).group(1)
        if ref in values:
            found.add(ref)
            head = cell.split('>', 1)[0].rstrip('/')
            head = re.sub(r'\s+t="[^"]*"', '', head)
            value = values[ref]
            if value is None:
                return head + '/>'
            if isinstance(value, str):
                return head + ' t="inlineStr"><is><t>' + escape(value) + '</t></is></c>'
            return head + '><v>' + str(value) + '</v></c>'
        if re.search(r'<f\b', cell):
            # Keep formulas byte-for-byte; discard obsolete September cached results.
            cell = re.sub(r'<v(?:\s[^>]*)?(?:/>|>.*?</v>)', '', cell)
        return cell
    result = CELL.sub(replace, xml)
    if set(values) != found:
        raise ValueError('模板缺少单元格：' + ', '.join(sorted(set(values) - found)))
    return result


def generate(template, output, events, now):
    template, output = Path(template), Path(output)
    if template.resolve() == output.resolve():
        raise ValueError('不能覆盖原始模板。')
    days = select_days(events, now)
    values = {'X2': now.year, 'AB2': now.month, 'I49': calendar.monthrange(now.year, now.month)[1]}
    for day in range(1, 32):
        row = day + 17
        for col in ('E', 'I', 'J', 'K', 'L', 'Y'):
            values[f'{col}{row}'] = None
        record = days.get(day)
        if not record:
            continue
        values[f'E{row}'] = '出勤（Bosch）'
        values[f'Y{row}'] = 'ETCとVICS開発'
        for kind, cols in [('startup', ('I', 'J')), ('shutdown', ('K', 'L'))]:
            if kind in record:
                values[f'{cols[0]}{row}'] = record[kind].hour
                values[f'{cols[1]}{row}'] = record[kind].minute
    with ZipFile(template) as source:
        sheet = patch_sheet(source.read('xl/worksheets/sheet1.xml').decode('utf-8'), values)
        workbook = source.read('xl/workbook.xml').decode('utf-8')
        workbook = re.sub(r'<calcPr\b[^>]*/>', '<calcPr calcMode="auto" fullCalcOnLoad="1" forceFullCalc="1"/>', workbook)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental replacement of manually edited reports.
        with output.open('xb') as target:
            with ZipFile(target, 'w') as dest:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == 'xl/worksheets/sheet1.xml':
                        data = sheet.encode('utf-8')
                    elif info.filename == 'xl/workbook.xml':
                        data = workbook.encode('utf-8')
                    dest.writestr(info, data)
    return days


def main():
    parser = argparse.ArgumentParser(description='自动生成当前月份的Quefy作业报告（Windows本地时间）')
    parser.add_argument('--template', type=Path, default=TEMPLATE)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'output')
    parser.add_argument('--events', type=Path, help='从JSON事件文件读取，用于离线生成或测试')
    args = parser.parse_args()
    now = datetime.now()
    try:
        events = json.loads(args.events.read_text(encoding='utf-8-sig')) if args.events else windows_events(now)
        name = f'Generate_Quefy株式会社{now.year}年{now.month:02d}月作業報告書(周尚軍).xlsx'
        output = args.output_dir / name
        if output.exists():
            output = output.with_stem(output.stem + now.strftime('_%Y%m%d_%H%M%S_%f'))
        days = generate(args.template, output, events, now)
        print(f'已生成：{output}\n已填写 {len(days)} 天；无记录日期保持空白。请用Excel打开以重新计算日期和工时。')
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f'错误：{exc}\n')


if __name__ == '__main__':
    main()
