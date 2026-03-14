# 中药材全国追踪

这是一个面向 Cloudflare Pages 的静态站骨架，当前围绕三块内容来搭建：

- `产地行情`
- `市场行情`
- `行业热点`

## 目录

- `public/index.html`：前端页面
- `public/data/dashboard.json`：前端读取的数据文件
- `scripts/build_dashboard_data.py`：从 Excel 生成 `dashboard.json`
- `scripts/import_openclaw_origin.py`：把 OpenClaw 抓取缓存转换成网站可用的产地行情 JSON
- `scripts/update_from_openclaw.py`：一键从 OpenClaw 缓存更新网站数据
- `scripts/publish_openclaw_update.py`：更新产地行情并自动提交、推送到 GitHub
- `data-source/latest.xlsx`：建议放在仓库里的最新 Excel 数据源
- `content/hotspots.json`：行业热点输入文件，当前默认为空数组
- `content/openclaw_origin.json`：OpenClaw 产地行情缓存导入结果

## 更新数据

先用 Excel 生成静态 JSON：

```bash
python3 scripts/build_dashboard_data.py
```

默认优先读取 `data-source/latest.xlsx`。如果这个文件不存在，脚本会再尝试你当前桌面的那份 Excel。

如果要把 OpenClaw 的抓取结果并入 `产地行情`，可以直接运行：

```bash
python3 scripts/update_from_openclaw.py --workspace /Users/bohao/.openclaw/workspace
```

这条命令会自动：

- 读取 OpenClaw 最新的 `tmp_herb_*.json` 或 `herb_market_brief_*.json`
- 提取适合 `产地行情` 的记录
- 生成 `content/openclaw_origin.json`
- 重建 `public/data/dashboard.json`

如果要继续自动发布到 GitHub，可以运行：

```bash
python3 scripts/publish_openclaw_update.py --workspace /Users/bohao/.openclaw/workspace
```

这条命令会在数据变化时只提交：

- `content/openclaw_origin.json`
- `public/data/dashboard.json`

然后推送到 `main`，Cloudflare Pages 会自动重新部署。

如果后面开始维护行业热点，可以把 `content/hotspots.json` 改成这样的结构：

```json
[
  {
    "date": "2026-03-14",
    "title": "某省发布中药材产业扶持新政",
    "kind": "政策",
    "summary": "提炼一两句重点内容。",
    "source": "政府网站",
    "url": "https://example.com/article",
    "herb": "黄芪",
    "location": "甘肃"
  }
]
```

## 本地预览

```bash
python3 -m http.server 8080 --directory public
```

然后打开 `http://localhost:8080`。
