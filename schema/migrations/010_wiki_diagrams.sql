-- Schema 9 -> 10: diagrams and images in wiki pages (docs/knowledge_wiki.md, step 3b). They're blocks in a
-- section like statements, so they're kept as statements of their own kind: their citations, labels, hiding,
-- links and search are the statements'. The description or file goes in block, their words in text.
-- store.py runs this in one transaction and backs the store up first.

ALTER TABLE wiki_statements ADD COLUMN kind TEXT CHECK (kind IS NULL OR kind IN ('diagram', 'image'));
ALTER TABLE wiki_statements ADD COLUMN block TEXT CHECK (block IS NULL OR json_valid(block));

UPDATE schema_version SET version = 10;
