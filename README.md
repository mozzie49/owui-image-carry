# Open WebUI Image Carry — experimental

Make an Open WebUI JSON chat export carry its uploaded image bytes, rather than only paths that point back to the old server.

**Status: experimental, not a complete server migration tool.** The [synthetic backend check](https://github.com/mozzie49/owui-image-carry/actions/runs/36883534349) passed against real Open WebUI 0.11.4 upload, file-authorization, export and import routes, and its continuation-message preprocessing. Image bytes and the selected conversation branch are preserved. Browser rendering and real-user trial are not yet verified. Do not delete your source instance or original export.

## Why this exists

[Open WebUI issue #20119](https://github.com/open-webui/open-webui/issues/20119) describes two users losing images when moving a conversation to another instance. One also cannot continue the imported conversation. This project targets that specific workflow, rather than whole-server database migration or exporting a readable PDF.

It replaces supported uploaded-image references with inline image data in both `history.messages` and the legacy message list. Message text, IDs and branches are preserved. It reads the source and creates a new JSON file; it does not modify either server or import automatically.

## Try only with a disposable example first

Python 3.11 or newer:

```sh
git clone https://github.com/mozzie49/owui-image-carry.git
cd owui-image-carry
python -m pip install -r requirements.txt
python carry.py original-export.json portable-export.json --source https://your-open-webui.example
```

Enter an **existing** source API token at the hidden prompt in an interactive terminal. The tool does not create or save a token. It sends that token only to the explicitly supplied origin, refuses redirects and reads canonical `/api/v1/files/{id}/content` endpoints. Remote instances require HTTPS. If the source runs on this same computer, literal loopback HTTP is also allowed, for example `--source http://127.0.0.1:8080`; HTTP to a LAN address or other hostname is refused. If your administrator does not permit API tokens, this mode is unavailable; do not change permissions just to try a prototype.

Keep the original export. On a disposable destination, use Open WebUI's normal JSON import. Verify the images and selected branch, then try a follow-up message. Importing repeatedly may create duplicate chats. This tool does not remove duplicates or delete either copy.

### Token-free local fixture / advanced offline mode

Try the included made-up conversation and tiny blue image without an account or token:

```sh
python carry.py demo-export.json demo-portable.json --asset-map demo-assets.json
```

The demo contains one image and two assistant response branches. The selected branch ends with “Keep the image in context.” The source reference has no corresponding file on a clean destination; the packed export carries the actual PNG bytes.

An asset-map JSON maps exported file IDs to image paths relative to that map:

```json
{"source-image": "synthetic.png"}
```

```sh
python carry.py original-export.json portable-export.json --asset-map assets.json
```

This is useful when you already have the corresponding images locally. It cannot recover bytes absent from both the original instance and your files.

## Deliberately narrow limits

- Tested data-model version: Open WebUI 0.11.4; schema compatibility with other versions is not promised
- Uploaded PNG, JPEG, GIF and WebP attachments only; no documents, RAG data, audio/video, arbitrary external images, generated-image Markdown links or complete server settings
- Remote mode supports HTTPS (or literal loopback HTTP), root-mounted instances and an already-authorized source token; no insecure TLS option, cookie scraping or token persistence
- At most 100 chats and 100 distinct images; 10 MiB per image, 20 megapixels per image, 50 MiB total image bytes, 50 MiB input JSON and 150 MiB output JSON
- All supported images must be available; missing, unauthorized, unsupported or oversized inputs fail instead of producing a silently incomplete success
- Existing output files are never overwritten
- Inline data increases JSON size. Original file-record IDs are not recreated on the destination; this is not a full attachment-database backup

## Privacy

The output contains your private conversation text and actual images. Do not publish it in issues, analytics, demos or public storage. The tool has no telemetry, hosted service or model calls. Network mode performs only source image GET requests; local-map mode performs no network requests. The source API token is entered locally and is not added to the export. New output files use owner-only permissions on systems that support them; secrets already present in your original conversation are not detected or removed.

For bug reports, use made-up text and a tiny synthetic image, never private chat exports or credentials.

## Verification

```sh
python -m unittest -v test_pack_images test_carry
```

`check_real_routes.py` is a separate integration harness using the installed official Open WebUI package and two fresh databases. It mounts real import/export/file routers with synthetic user identity overrides; actual file authorization remains enabled. It uses no real model endpoint. A passing backend fixture would not establish browser rendering, authentication-flow coverage or real-user success.

The development process is AI-assisted. This is an independent project, not affiliated with or endorsed by Open WebUI. Original helper code is MIT licensed. The integration dependency Open WebUI retains its own license and branding; its source is not bundled here.

## 中文说明

这是针对“迁移 Open WebUI 对话后图片丢失”的实验工具。真实上传、权限、导出、导入接口以及继续对话的消息预处理已通过合成样例检查；浏览器显示和真实用户试用尚未验证。仓库自带虚构对话和小图片，不需要账号即可尝试转换。请保留原始导出和原服务器，不要把私人对话、图片或 API token 提交到公开 issue。
