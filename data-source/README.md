把最新的 Excel 放在这里，并命名为 `latest.xlsx`。

推荐流程：

1. 用最新整理好的表替换这个目录里的 `latest.xlsx`
2. 运行：

```bash
python3 scripts/build_dashboard_data.py
```

3. 提交并推送到 GitHub，Cloudflare Pages 会自动重新部署

如果你不想固定文件名，也可以手动指定：

```bash
python3 scripts/build_dashboard_data.py --input "/你的路径/某个文件.xlsx"
```
