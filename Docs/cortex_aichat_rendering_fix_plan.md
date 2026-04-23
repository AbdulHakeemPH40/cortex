# Cortex AI Chat Rendering Fix Plan

## Goal
Fix the AI chat rendering pipeline so the assistant response displays clean Markdown, code blocks, and tables without leaking raw symbols such as `**`, `---`, broken pipes, or partial HTML.

## What is currently going wrong
Your current chat UI already contains a Markdown pipeline with custom `marked` renderers, a heavy `normalizeMarkdownText()` preprocessor, a fallback Markdown formatter, and post-processing for syntax highlighting and code headers. The problem is not that Markdown is missing; the problem is that the pipeline is too aggressive and is modifying content in too many places, which causes corrupted tables, broken code block containers, and raw markdown artifacts leaking into the final DOM.

## Root causes

### 1) Table cleanup is too aggressive
Your normalization logic rewrites pipes (`|`), separators (`---`), and row boundaries in many different passes. When the model emits a table with extra spaces, a missing separator, or a table that is followed by normal text, the current regex chain can:
- split rows incorrectly,
- inject separator lines in the wrong place,
- turn normal text into table rows,
- or leave `-----` visible in the output.

### 2) Markdown is rendered, then mutated again
The response is parsed, then syntax-highlighted, then code headers are injected, then suggestion chips are injected, and then `innerHTML` is rewritten again. That increases the chance of DOM loss, especially for nested code blocks and tables.

### 3) Code fences are not isolated early enough
Code blocks must be protected before any markdown cleanup touches the text. If table-fixing regexes run across fenced code content, the fenced content is damaged before parsing.

### 4) Raw HTML and malformed AI artifacts are not normalized with clear boundaries
The model sometimes outputs mixed HTML, markdown, and plain text in one turn. The current cleanup logic needs a strict rule: only normalize plain text outside code fences; never rewrite inside fenced code.

## Fix strategy

## A. Split the renderer into 4 strict stages

### Stage 1: Raw text sanitation
Only do safe cleanup here:
- remove zero-width/invisible characters,
- normalize line endings,
- trim trailing control characters,
- remove obviously broken HTML fragments if they are not inside code fences.

Do **not** do table repair, heading repair, or pipe rewriting here.

### Stage 2: Fence protection
Before any Markdown mutation, extract fenced code blocks and replace them with placeholders.

Example approach:
```js
const codeBlocks = [];
text = text.replace(/```([\w-]*)\n([\s\S]*?)\n?```/g, (_, lang, code) => {
  const id = codeBlocks.length;
  codeBlocks.push({ lang: lang || 'text', code });
  return `%%CODEBLOCK_${id}%%`;
});
```

This guarantees table-fixing regexes cannot corrupt code blocks.

### Stage 3: Markdown normalization on non-code text only
Apply only a small set of targeted fixes:
- `** text**` -> `**text**`
- `###title` -> `### title`
- `1)` -> `1.`
- fix one malformed table row at a time, not the whole document.

For tables, use a block-based parser:
- detect a consecutive block of lines containing pipes,
- verify it has a header row and separator row,
- only then normalize spacing inside the table block.

### Stage 4: Parse once, then post-process DOM only
Render Markdown once with `marked`.
After that:
- apply code block headers,
- apply syntax highlighting once,
- enhance links/chips only inside text nodes or safe segments,
- avoid reassigning `innerHTML` multiple times unless absolutely necessary.

## B. Replace global table regexes with block parsing
Instead of many global regex passes, use this rule:
1. Split text into lines.
2. Walk line-by-line.
3. When a line starts with `|` or looks like a table row, collect the entire table block.
4. Normalize only that block.
5. Leave non-table text untouched.

Minimum table rules:
- A valid table needs at least 2 columns.
- A table header should be followed by a separator row.
- If the separator row is missing, generate one once.
- Never convert lines outside the block into table rows.

## C. Keep code blocks visually consistent
Your code renderer should always output the same structure:
```html
<div class="code-block-wrapper">
  <div class="code-header copy-only">...</div>
  <pre data-lang="python"><code class="hljs language-python">...</code></pre>
</div>
```

That means:
- the copy header must be injected every time,
- the wrapper must be stable,
- and the code block container CSS must target this exact DOM structure.

## D. Add a safety fallback for broken AI output
If the main Markdown parser fails:
- show plain text with escaped HTML,
- preserve line breaks,
- preserve code fences as readable blocks,
- do not attempt aggressive table repair in fallback mode.

## Exact code changes to make

### 1) Simplify `normalizeMarkdownText()`
Keep only safe sanitization and fence-preserving transforms.
Remove or narrow down these kinds of rules:
- broad pipe rewrites,
- global `---` cleanup across all lines,
- aggressive `|...|` normalization,
- any regex that can match inside code fences.

### 2) Add a table-block parser
Create a helper like:
```js
function normalizeTableBlock(lines) {
  // detect valid rows
  // normalize spacing
  // generate separator if needed
  // return cleaned lines
}
```

### 3) Rebuild the renderer flow
Recommended order:
```js
raw text -> sanitize -> extract code fences -> normalize markdown -> restore code fences -> marked.parse -> post-process DOM -> inject headers -> highlight
```

### 4) Remove duplicate rendering passes
Do not render markdown, then rebuild it again with another fallback parser unless the primary parser fails.

### 5) Make code header injection idempotent
Your code header injector should skip already wrapped code blocks and never create duplicate wrappers.

## CSS checks
Make sure these containers exist and are styled:
- `.message-content`
- `.code-block-wrapper`
- `.code-header`
- `.code-copy-btn`
- `.table-wrapper`
- `.md-blockquote`
- `.inline-code`
- `.streaming-cursor`

Also ensure tables have:
- horizontal overflow handling,
- fixed spacing,
- no accidental wrapping that breaks the layout.

## Regression tests to add
Use these inputs to verify rendering:

### Test 1: Table with separators
```md
| Aspect | Python | Rust |
| --- | --- | --- |
| Speed | Slow | Fast |
```
Expected: real table, no raw `---` text.

### Test 2: Table with missing blank line
```md
Intro text
| A | B |
| --- | --- |
| 1 | 2 |
```
Expected: table starts on its own block, no merged paragraph/table.

### Test 3: Code block containing pipes
```md
```bash
echo "a | b | c"
```
```
Expected: pipes remain inside the code block, not treated as a table.

### Test 4: Broken bold text
```md
** Python** is great
```
Expected: `Python` is bolded cleanly or rendered as plain text without stray `**`.

### Test 5: Mixed HTML and markdown
```md
<h3>Title</h3>
- item one
```
Expected: HTML fragments do not break the list rendering.

## Acceptance criteria
The fix is complete when:
- raw `**` does not appear in normal chat output,
- `-----` does not appear inside tables,
- code blocks always get their card/header,
- tables stay in one block and do not spill into following text,
- fallback rendering remains readable even when the model output is malformed.

## Priority order
1. Protect code fences.
2. Replace broad table regexes with block parsing.
3. Make rendering one-pass.
4. Keep header injection idempotent.
5. Add regression tests.

## Recommended implementation note
Do not try to repair every malformed AI line with regex. That approach causes the exact rendering corruption you are seeing. Use structural parsing for tables and code fences, and keep the cleanup stage minimal.
