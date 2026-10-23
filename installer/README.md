# 安装器

`AudioAlign.iss` 是 Inno Setup 6 脚本，按用户安装到 `%LOCALAPPDATA%\Programs\AudioAlign`，不需要管理员权限。

```powershell
# 先构建 onedir
python tools\build_desktop.py

# 编译安装包（Inno Setup 6 的 ISCC.exe）
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\AudioAlign.iss
```

产物：`dist\AudioAlign-Setup-0.1.0.exe`。

注意：当前开发机的 GitHub/官方下载源被网络阻断，Inno Setup 尚未安装；脚本已就绪。若本机已有 Inno Setup，直接跑上面的 ISCC 命令即可。
