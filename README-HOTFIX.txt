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
