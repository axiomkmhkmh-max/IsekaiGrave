ISEKAI GRAVE v4.1.1 — DATABASE HOTFIX

Contents:
- IsekaiGrave-main/database.py

Fix:
The previous v4.1 database.py accidentally contained a literal "\\n" inside
the comment on the wevents binding line. This caused the chronicle assignment
to be swallowed by the comment, so Store had no `chronicle` attribute.

Install:
1. Stop/redeploy the Railway service.
2. Extract this ZIP at the project root, preserving the IsekaiGrave-main/
   folder path if your repository uses that folder, or copy database.py
   over the existing root database.py if the app root is the project folder.
3. Commit/push the replacement and redeploy.
4. Check logs: startup should pass `await store.ensure_indexes()`.

No database data is deleted. This only restores the missing collection handle.


IMAGE DELIVERY HOTFIX
====================
The exploration/menu callbacks use CbMsg, a Message adapter. It previously supported text replies but not reply_photo, so image sending raised AttributeError and was swallowed by world_art.send_world_art. CbMsg now forwards reply_photo to the original Telegram message's answer_photo method.

After deployment, check Railway Deploy Logs for `Artwork delivered: ... source=...`. `source=local-fallback` means Telegram delivery works but no remote image endpoint is configured or the provider request failed. To get cinematic AI artwork, configure IMAGE_API_URL, IMAGE_API_KEY (if required), and IMAGE_MODEL using a compatible image-generation provider. Never put secrets in source code.
