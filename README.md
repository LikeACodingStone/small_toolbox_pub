## 🛠️ Toolbox Overview

Here is a curated list of scripts and utilities available in this repository. Each tool is contained within its own directory with independent configurations.

| Tool Name | Category | Tech Stack | Description | Status |
| :--- | :--- | :--- | :--- | :---: |
| [audio-clipper](./audio-clipper/) | Audio | `Python` `FFmpeg` | Automatically segments long audio files based on silence detection and outputs optimized MP3s. | 🟢 Stable |
| [sys-monitor](./sys-monitor/) | DevOps | `Go` `InfluxDB` | A lightweight daemon that monitors CPU/Memory usage and streams metrics to a local dashboard. | 🟡 Beta |
| [web-scraper](./web-scraper/) | Automation | `Node.js` `Puppeteer` | Scrapes dynamic e-commerce data and exports clean JSON formatted reports daily. | 🟢 Stable |
| [link-checker](./link-checker/) | Security | `Shell` `Curl` | A dead-simple script to recursively scan markdown files for broken URLs and hyperlinks. | 🔴 Archived |
| [img-compressor](./img-compressor/) | Image | `Python` `Pillow` | Bulk compresses PNG/JPG images in a folder without noticeable quality loss. | 🔵 Planning |

---

### 💡 Table Legend (Status)
* 🟢 **Stable**: Fully functional, thoroughly tested, and ready for daily production use.
* 🟡 **Beta**: Working, but actively developing new features or fixing occasional edge-case bugs.
* 🔵 **Planning**: Concept/Placeholder folder. Code is not yet implemented or in early drafting.
* 🔴 **Archived**: Discontinued or deprecated, kept only for historical reference.