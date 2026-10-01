# Open WebUI Image Carry — experimental

Make an Open WebUI JSON chat export carry its uploaded image bytes, rather than only paths that point back to the old server.

**Status: reproduction prototype, not a verified complete migration tool yet.** The local check uses the real Open WebUI 0.11.4 import/database code and preserves the synthetic image and conversation branches. Full route/continuation verification is being added in CI. Browser rendering and real-user trial are not yet verified. Do not delete your source instance or original export.

## Why this exists

[Open WebUI issue #20119](https://github.com/open-webui/open-webui/issues/20119) describes two users losing images when moving a conversation to another instance. One also cannot continue the imported conversation. This project targets that specific workflow, rather than whole-server database migration or exporting a readable PDF.

It replaces supported uploaded-image references with inline image data in both `history.messages` and the legacy message list. Message text, IDs and branches are preserved. It reads the source and creates a new JSON file; it does not modify either server or import automatically.

## Try only with a disposable example first

Python 3.11 or newer:

```sh
python -m pip install -r requirements.txt
python carry.py original-export.json portable-export.json --source https://your-open-webui.example
```

Enter an **existing** source API token at the hidden prompt. The tool does not create or save a token. It sends that token only to the explicitly supplied HTTPS origin, refuses redirects and reads canonical `/api/v1/files/{id}/content` endpoints. If your administrator does not permit API tokens, this mode is unavailable; do not change permissions just to try a prototype.

Keep the original export. On a disposable destination, use Open WebUI's normal JSON import. Verify the images and selected branch, then try a follow-up message. Importing repeatedly may create duplicate chats. This tool does not remove duplicates or delete either copy.

### Token-free local fixture / advanced offline mode

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
- Remote mode supports HTTPS, root-mounted instances and an already-authorized source token; no insecure TLS option, cookie scraping or token persistence
- At most 100 chats and 100 distinct images; 10 MiB per image, 20 megapixels per image, 50 MiB total image bytes, 50 MiB input JSON and 150 MiB output JSON
- All supported images must be available; missing, unauthorized, unsupported or oversized inputs fail instead of producing a silently incomplete success
- Existing output files are never overwritten
- Inline data increases JSON size. Original file-record IDs are not recreated on the destination; this is not a full attachment-database backup

## Privacy

The output contains your private conversation text and actual images. Do not publish it in issues, analytics, demos or public storage. The tool has no telemetry, hosted service or model calls. Network mode performs only source image GET requests; local-map mode performs no network requests. Credentials are entered locally and are not included in the export.

For bug reports, use made-up text and a tiny synthetic image, never private chat exports or credentials.

## Verification

```sh
python -m unittest -v test_pack_images test_carry
```

`check_real_routes.py` is a separate integration harness using the installed official Open WebUI package and two fresh databases. It mounts real import/export/file routers with synthetic user identity overrides; actual file authorization remains enabled. It uses no real model endpoint. A passing backend fixture would not establish browser rendering, authentication-flow coverage or real-user success.

The development process is AI-assisted. This is an independent project, not affiliated with or endorsed by Open WebUI. Original helper code is MIT licensed. The integration dependency Open WebUI retains its own license and branding; its source is not bundled here.

## 中文说明

这是针对“迁移 Open WebUI 对话后图片丢失”的实验原型。目前已通过真实数据库导入层的合成样例检查，完整接口、继续对话和浏览器显示仍需分别验证。请保留原始导出和原服务器，先用虚构对话、小图片和临时目标实例试验。不要把私人对话、图片或 API token 提交到公开 issue。
