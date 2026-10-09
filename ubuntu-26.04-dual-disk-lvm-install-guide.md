# Ubuntu 26.04 双硬盘合并 LVM 重装操作手册

## 1. 文档目的

本文说明如何在重新安装 Ubuntu 26.04 LTS 时，将两块约 1.8 TB 的硬盘组成一个 LVM 存储池，并创建一个主要逻辑卷作为根文件系统 `/`。

目标硬盘：

- `/dev/sda`：约 1.8 TB
- `/dev/sdb`：约 1.8 TB

完成后可用原始容量约为 3.6 TB，即约 3.27 TiB。EFI、`/boot`、LVM 元数据和 ext4 文件系统会占用少量空间，所以实际显示容量会略小。

> [!CAUTION]
> 本操作会彻底清空 `/dev/sda` 和 `/dev/sdb`。执行前必须将重要数据备份到不参与安装的第三块硬盘、NAS 或其他计算机，并确认备份能够正常读取。

> [!WARNING]
> 本方案是 LVM 线性容量合并，不是 RAID，也不提供磁盘冗余。任意一块硬盘损坏，都可能导致整个根文件系统无法启动或无法挂载。LVM 快照也不能替代异机备份。

## 2. 最终磁盘布局

本文假设计算机使用 UEFI 启动和 GPT 分区表。

| 设备 | 建议大小 | 文件系统或类型 | 挂载点或用途 |
|---|---:|---|---|
| `/dev/sda1` | 约 1 GiB | FAT32 / EFI System Partition | `/boot/efi` |
| `/dev/sda2` | 2 GiB | ext4 | `/boot` |
| `/dev/sda3` | 剩余全部 | LVM Physical Volume | 加入 `ubuntu-vg` |
| `/dev/sdb1` | 全盘 | LVM Physical Volume | 加入 `ubuntu-vg` |
| `ubuntu-vg/root` | VG 的绝大部分或全部 | ext4 | `/` |

EFI 系统分区不能放在 LVM 内，因此不能把磁盘上的每一个分区都放入 LVM。上述布局会把除启动分区外的主要空间合并成一个 LVM 卷组，并创建一个大的根逻辑卷。

LVM 层次关系如下：

```text
/dev/sda3 ─┐
           ├─ ubuntu-vg ── root ── ext4 ── /
/dev/sdb1 ─┘
```

## 3. 安装前准备

### 3.1 备份数据

1. 将两块目标盘上的重要数据复制到其他设备。
2. 随机打开若干备份文件，确认备份不是空文件且可以正常读取。
3. 记录应用配置、SSH 密钥、数据库备份和加密密钥。
4. 将备份盘从待安装计算机上断开，避免安装时误选。

Ubuntu 官方同样强调，重新分区可能导致磁盘上的全部数据丢失：

- [Ubuntu Server 基础安装说明](https://ubuntu.com/server/docs/tutorial/basic-installation/)

### 3.2 记录硬盘身份

如果旧系统仍可启动，执行：

```bash
lsblk -d -o NAME,SIZE,MODEL,SERIAL,TRAN
lsblk -f
```

记录两块目标硬盘的：

- 容量
- 型号
- 序列号

不要只依赖 `/dev/sda` 和 `/dev/sdb` 的名称。从安装 U 盘启动后，Linux 可能重新分配设备名称。

建议临时断开所有不参与安装的内部数据盘和移动硬盘，只保留：

- 两块目标硬盘
- Ubuntu 安装 U 盘

### 3.3 下载 Ubuntu 26.04 安装镜像

建议使用 Ubuntu Server 安装镜像，因为其自定义存储界面明确支持创建跨多个磁盘的 LVM 卷组。

下载文件：

```text
ubuntu-26.04-live-server-amd64.iso
```

官方下载地址：

- [Ubuntu 26.04 LTS 发布目录](https://releases.ubuntu.com/releases/26.04/)
- [Ubuntu Server 下载页面](https://ubuntu.com/download/server)

下载后计算 SHA-256：

```bash
sha256sum ubuntu-26.04-live-server-amd64.iso
```

将结果与官方下载目录中的 `SHA256SUMS` 比较。

### 3.4 制作安装 U 盘

可以使用以下工具：

- Windows：Rufus
- Ubuntu：Disks（磁盘）
- Windows、macOS 或 Linux：balenaEtcher

这是镜像写入操作，不能只是把 ISO 文件复制到 U 盘。

## 4. 以 UEFI 模式启动安装程序

1. 插入安装 U 盘。
2. 重启计算机并进入启动菜单，常见按键为 `F12`、`Esc`、`F2` 或 `F10`。
3. 选择名称类似下面的启动项：

   ```text
   UEFI: <U盘名称>
   ```

4. 不要选择不带 `UEFI` 字样的 Legacy 或 CSM 启动项。

进入安装程序后，可以按 `F2` 进入 Shell 并检查启动模式：

```bash
test -d /sys/firmware/efi && echo UEFI || echo Legacy
```

预期输出：

```text
UEFI
```

如果输出 `Legacy`，应退出安装程序，重新从 UEFI 启动项启动 U 盘。

## 5. 安装程序中的基础设置

依次完成以下页面：

1. 选择语言。
2. 如果提示更新安装器，建议联网更新。
3. 选择键盘布局。
4. 配置网络。
5. 配置代理；不使用代理时留空。
6. 选择 Ubuntu 软件镜像源。

进入 `Storage configuration` 后，不要选择自动使用单块整盘的方式。

## 6. 配置双硬盘 LVM

### 6.1 选择自定义存储布局

在 `Storage configuration` 页面选择：

```text
Custom storage layout
```

Ubuntu 安装器的官方存储配置说明：

- [Configuring storage](https://canonical-subiquity.readthedocs-hosted.com/en/latest/howto/configure-storage.html)

### 6.2 再次核对目标磁盘

在磁盘列表中检查两块目标盘的容量、型号和序列号。

> [!CAUTION]
> 安装 U 盘也会出现在设备列表中。绝对不要把安装 U 盘或备份盘加入 LVM 卷组。

### 6.3 重建 GPT 分区表

分别选择两块目标硬盘，并执行：

```text
Reformat → GPT
```

此操作将安排删除两块硬盘上的现有分区。

### 6.4 配置第一块硬盘

选择作为启动盘的第一块硬盘，执行：

```text
Use As Boot Device
```

在 UEFI 模式下，安装器会自动创建 EFI System Partition，并把 GRUB 安装到该分区。官方文档说明，安装器自动创建的 ESP 最小为 538 MiB。

然后在第一块硬盘的 `free space` 中创建 `/boot` 分区：

```text
Size:       2G
Format:     ext4
Mount:      /boot
```

继续在剩余 `free space` 中创建一个供 LVM 使用的分区：

```text
Size:       留空，使用剩余全部空间
Format:     Leave unformatted
Mount:      不设置
```

### 6.5 配置第二块硬盘

在第二块硬盘的 `free space` 中选择 `Add GPT Partition`，创建一个占满全盘的未格式化分区：

```text
Size:       留空，使用全部空间
Format:     Leave unformatted
Mount:      不设置
```

### 6.6 创建 LVM 卷组

选择：

```text
Create volume group (LVM)
```

填写：

```text
Name: ubuntu-vg
```

在设备列表中同时选中：

- 第一块硬盘上的大容量未格式化分区
- 第二块硬盘上的大容量未格式化分区

确认两个分区都属于 `ubuntu-vg`。

本文默认不启用磁盘加密。如果决定启用 LUKS，必须将解锁密码保存在本机之外；密码丢失后通常无法恢复数据。

### 6.7 创建根逻辑卷

选择 `ubuntu-vg` 下的 `free space`，创建逻辑卷：

```text
Name:       root
Format:     ext4
Mount:      /
```

容量有两种选择：

#### 方案 A：使用全部空间

```text
Size: 留空
```

根文件系统会使用卷组中的全部可用空间。这最符合“一个大卷使用全部容量”的目标，但以后无法直接创建新的 LV 或 LVM 快照。

#### 方案 B：预留 50–100 GiB，推荐

在 `Size` 中填写略小于 VG 总容量的值，为 LVM 快照或后续调整留出 50–100 GiB。

以后可以把全部剩余空间在线扩展给根卷：

```bash
sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/root
```

Ubuntu 官方也建议在卷组中保留一些空间，以便创建快照或其他逻辑卷。

### 6.8 安装前最终检查

最终界面应大致显示：

```text
/dev/sda
  EFI System Partition       /boot/efi
  ext4                       /boot
  LVM PV                     ubuntu-vg

/dev/sdb
  LVM PV                     ubuntu-vg

ubuntu-vg
  root  ext4                 /
```

点击 `Done` 前确认：

- 只有两块目标硬盘会被清空。
- `/boot/efi` 位于 EFI System Partition。
- `/boot` 位于第一块硬盘的独立 ext4 分区。
- 两个大分区都属于 `ubuntu-vg`。
- `ubuntu-vg/root` 格式化为 ext4 并挂载到 `/`。
- 没有选择安装 U 盘或备份盘。

确认无误后选择：

```text
Done → Continue
```

从这里开始，磁盘修改将实际执行。

## 7. 完成系统安装

继续完成：

1. 设置主机名。
2. 创建管理员用户和密码。
3. 按需安装 OpenSSH Server。
4. 按需选择额外软件。
5. 等待安装和更新完成。
6. 选择 `Reboot`。
7. 出现提示后拔出安装 U 盘并按 `Enter`。

## 8. 安装后的验证

登录新系统后执行：

```bash
sudo pvs
sudo vgs
sudo lvs -o lv_name,vg_name,lv_size,segtype,devices
lsblk -f
df -hT /
```

正确结果应满足：

- `pvs` 显示两个 Physical Volume。
- 两个 PV 都属于 `ubuntu-vg`。
- `vgs` 显示的总容量接近两块硬盘容量之和。
- `ubuntu-vg/root` 挂载在 `/`。
- `lvs` 的 `devices` 字段能够看到两块硬盘上的 LVM 分区。
- `segtype` 为 `linear`。

检查启动分区：

```bash
findmnt /
findmnt /boot
findmnt /boot/efi
```

检查交换空间：

```bash
swapon --show
```

## 9. 安装图形桌面（可选）

Ubuntu Server ISO 默认不安装图形界面。如果需要标准 Ubuntu GNOME 桌面，联网后执行：

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install ubuntu-desktop
sudo reboot
```

重启后，系统仍使用相同的双硬盘 LVM 布局。

## 10. 风险与替代方案

### 10.1 当前方案：LVM linear

- 可用容量：约两块盘之和
- 容错能力：无
- 任一磁盘故障影响：整个根文件系统可能不可用
- 性能：不是 RAID 0，不保证读写速度翻倍

Ubuntu Server 安装器创建的普通逻辑卷默认采用 `linear` 布局：

- [Subiquity 的 LVM 限制说明](https://canonical-subiquity.readthedocs-hosted.com/en/latest/howto/configure-storage.html#limitations-and-workarounds)

### 10.2 如果更重视可靠性：RAID1 + LVM

- 可用容量：约 1.8 TB
- 容错能力：允许其中一块磁盘故障
- 适用场景：重要业务数据、缺少及时异机备份的系统

### 10.3 如果更重视容量和性能：RAID0 + LVM

- 可用容量：约 3.6 TB
- 容错能力：无
- 性能：可能高于线性 LVM
- 任一磁盘故障影响：整个阵列不可用

无论选择哪种方案，都应保留独立于本机的定期备份。

## 11. 安装检查清单

安装前：

- [ ] 已完成异机或离线备份
- [ ] 已验证备份可读
- [ ] 已记录两块目标硬盘的型号和序列号
- [ ] 已断开其他数据盘和备份盘
- [ ] 已校验 Ubuntu ISO 的 SHA-256
- [ ] 安装 U 盘以 UEFI 模式启动

提交磁盘修改前：

- [ ] 两块目标盘均使用 GPT
- [ ] 第一块盘已设置为 Boot Device
- [ ] EFI System Partition 正确
- [ ] `/boot` 为独立 ext4 分区
- [ ] 两个 LVM 分区均加入 `ubuntu-vg`
- [ ] `ubuntu-vg/root` 挂载到 `/`
- [ ] 删除清单中没有安装 U 盘或其他数据盘

安装后：

- [ ] `pvs` 显示两个 PV
- [ ] `vgs` 显示合并后的容量
- [ ] `lvs` 显示 `root` 使用两个磁盘
- [ ] `/`、`/boot` 和 `/boot/efi` 挂载正确
- [ ] 已配置并测试系统备份

## 12. 参考资料

- [Ubuntu 26.04 LTS 官方发布目录](https://releases.ubuntu.com/releases/26.04/)
- [Ubuntu Server 基础安装](https://ubuntu.com/server/docs/tutorial/basic-installation/)
- [Ubuntu 安装器存储配置](https://canonical-subiquity.readthedocs-hosted.com/en/latest/howto/configure-storage.html)
- [Ubuntu LVM 概念说明](https://documentation.ubuntu.com/server/explanation/storage/about-lvm/)
- [Ubuntu 逻辑卷管理说明](https://documentation.ubuntu.com/server/how-to/storage/manage-logical-volumes/)
