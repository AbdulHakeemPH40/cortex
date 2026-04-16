"""HTML IntelliSense provider for Cortex IDE.

Provides VS Code-style HTML completions including:
- Tag suggestions (<div>, <span>, etc.)
- Attribute suggestions (class, id, style, etc.)
- Attribute value suggestions
- Emmet abbreviation expansion
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import re


@dataclass
class HTMLCompletionItem:
    """Represents a single completion item."""
    label: str
    kind: str  # 'tag', 'attribute', 'value', 'emmet'
    detail: str
    insert_text: str
    documentation: str = ""
    sort_text: str = ""


# Self-closing (void) HTML tags - these don't have closing tags
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr"
}

# HTML5 Tag Definitions
HTML_TAGS: Dict[str, Dict] = {
    "!DOCTYPE": {
        "detail": "Document type declaration",
        "insert": "!DOCTYPE html>",
        "doc": "Defines the document type and HTML version"
    },
    "a": {
        "detail": "Anchor element",
        "insert": "a href=\"$1\">$2</a>",
        "doc": "Defines a hyperlink to other web pages, files, locations within the same page, email addresses, or any other URL."
    },
    "abbr": {
        "detail": "Abbreviation",
        "insert": "abbr title=\"$1\">$2</abbr>",
        "doc": "Represents an abbreviation and optionally provides a full description for it."
    },
    "address": {
        "detail": "Contact information",
        "insert": "address>\n  $1\n</address>",
        "doc": "Indicates that the enclosed HTML provides contact information for a person or people, or for an organization."
    },
    "area": {
        "detail": "Image map area",
        "insert": "area shape=\"$1\" coords=\"$2\" href=\"$3\">",
        "doc": "Defines a hot-spot region on an image, and optionally associates it with a hypertext link.",
        "void": True
    },
    "article": {
        "detail": "Article content",
        "insert": "article>\n  $1\n</article>",
        "doc": "Represents a self-contained composition in a document, page, application, or site."
    },
    "aside": {
        "detail": "Sidebar content",
        "insert": "aside>\n  $1\n</aside>",
        "doc": "Represents a portion of a document whose content is only indirectly related to the document's main content."
    },
    "audio": {
        "detail": "Audio player",
        "insert": "audio controls>\n  <source src=\"$1\" type=\"audio/$2\">\n</audio>",
        "doc": "Used to embed sound content in documents."
    },
    "b": {
        "detail": "Bold text",
        "insert": "b>$1</b>",
        "doc": "Used to draw the reader's attention to the element's contents."
    },
    "base": {
        "detail": "Base URL",
        "insert": "base href=\"$1\">",
        "doc": "Specifies the base URL to use for all relative URLs in a document.",
        "void": True
    },
    "bdi": {
        "detail": "Bidirectional isolate",
        "insert": "bdi>$1</bdi>",
        "doc": "Tells the browser's bidirectional algorithm to treat the text it contains in isolation from its surrounding text."
    },
    "bdo": {
        "detail": "Bidirectional override",
        "insert": "bdo dir=\"$1\">$2</bdo>",
        "doc": "Overrides the current directionality of text."
    },
    "blockquote": {
        "detail": "Block quotation",
        "insert": "blockquote cite=\"$1\">\n  $2\n</blockquote>",
        "doc": "Indicates that the enclosed text is an extended quotation."
    },
    "body": {
        "detail": "Document body",
        "insert": "body>\n  $1\n</body>",
        "doc": "Represents the content of an HTML document."
    },
    "br": {
        "detail": "Line break",
        "insert": "br>",
        "doc": "Produces a line break in text (carriage-return).",
        "void": True
    },
    "button": {
        "detail": "Button",
        "insert": "button type=\"$1\">$2</button>",
        "doc": "An interactive element activated by a user with a mouse, keyboard, finger, voice command, or other assistive technology."
    },
    "canvas": {
        "detail": "Scriptable bitmap canvas",
        "insert": "canvas id=\"$1\" width=\"$2\" height=\"$3\"></canvas>",
        "doc": "Used to draw graphics via scripting (usually JavaScript)."
    },
    "caption": {
        "detail": "Table caption",
        "insert": "caption>$1</caption>",
        "doc": "Specifies the caption (or title) of a table."
    },
    "cite": {
        "detail": "Citation",
        "insert": "cite>$1</cite>",
        "doc": "Used to describe a reference to a cited creative work."
    },
    "code": {
        "detail": "Code fragment",
        "insert": "code>$1</code>",
        "doc": "Displays its contents styled in a fashion intended to indicate that the text is a short fragment of computer code."
    },
    "col": {
        "detail": "Table column",
        "insert": "col>",
        "doc": "Defines a column within a table.",
        "void": True
    },
    "colgroup": {
        "detail": "Column group",
        "insert": "colgroup>\n  <col>\n</colgroup>",
        "doc": "Defines a group of columns within a table."
    },
    "data": {
        "detail": "Machine-readable data",
        "insert": "data value=\"$1\">$2</data>",
        "doc": "Links a given piece of content with a machine-readable translation."
    },
    "datalist": {
        "detail": "Data list",
        "insert": "datalist id=\"$1\">\n  <option value=\"$2\">\n</datalist>",
        "doc": "Contains a set of option elements that represent the permissible or recommended options available to choose from within other controls."
    },
    "dd": {
        "detail": "Description details",
        "insert": "dd>$1</dd>",
        "doc": "Provides the description, definition, or value for the preceding term (dt) in a description list (dl)."
    },
    "del": {
        "detail": "Deleted text",
        "insert": "del>$1</del>",
        "doc": "Represents a range of text that has been deleted from a document."
    },
    "details": {
        "detail": "Disclosure widget",
        "insert": "details>\n  <summary>$1</summary>\n  $2\n</details>",
        "doc": "Creates a disclosure widget in which information is visible only when the widget is toggled into an 'open' state."
    },
    "dfn": {
        "detail": "Definition",
        "insert": "dfn>$1</dfn>",
        "doc": "Used to indicate the term being defined within the context of a definition phrase or sentence."
    },
    "dialog": {
        "detail": "Dialog box",
        "insert": "dialog>\n  $1\n</dialog>",
        "doc": "Represents a dialog box or other interactive component, such as a dismissible alert, inspector, or subwindow."
    },
    "div": {
        "detail": "Division/Container",
        "insert": "div>\n  $1\n</div>",
        "doc": "The generic container for flow content. It has no effect on the content or layout until styled in some way using CSS."
    },
    "dl": {
        "detail": "Description list",
        "insert": "dl>\n  <dt>$1</dt>\n  <dd>$2</dd>\n</dl>",
        "doc": "Represents a description list."
    },
    "dt": {
        "detail": "Description term",
        "insert": "dt>$1</dt>",
        "doc": "Specifies a term in a description or definition list."
    },
    "em": {
        "detail": "Emphasis",
        "insert": "em>$1</em>",
        "doc": "Marks text that has stress emphasis."
    },
    "embed": {
        "detail": "External content",
        "insert": "embed src=\"$1\" type=\"$2\">",
        "doc": "Embeds external content at the specified point in the document.",
        "void": True
    },
    "fieldset": {
        "detail": "Form field set",
        "insert": "fieldset>\n  <legend>$1</legend>\n  $2\n</fieldset>",
        "doc": "Used to group several controls as well as labels (label) within a web form."
    },
    "figcaption": {
        "detail": "Figure caption",
        "insert": "figcaption>$1</figcaption>",
        "doc": "Represents a caption or legend describing the rest of the contents of its parent figure element."
    },
    "figure": {
        "detail": "Self-contained content",
        "insert": "figure>\n  $1\n  <figcaption>$2</figcaption>\n</figure>",
        "doc": "Represents self-contained content, potentially with an optional caption."
    },
    "footer": {
        "detail": "Footer section",
        "insert": "footer>\n  $1\n</footer>",
        "doc": "Represents a footer for its nearest ancestor sectioning content or sectioning root element."
    },
    "form": {
        "detail": "Form",
        "insert": "form action=\"$1\" method=\"$2\">\n  $3\n</form>",
        "doc": "Represents a document section containing interactive controls for submitting information."
    },
    "h1": {
        "detail": "Heading level 1",
        "insert": "h1>$1</h1>",
        "doc": "Represents the highest level of section headings."
    },
    "h2": {
        "detail": "Heading level 2",
        "insert": "h2>$1</h2>",
        "doc": "Represents the second level of section headings."
    },
    "h3": {
        "detail": "Heading level 3",
        "insert": "h3>$1</h3>",
        "doc": "Represents the third level of section headings."
    },
    "h4": {
        "detail": "Heading level 4",
        "insert": "h4>$1</h4>",
        "doc": "Represents the fourth level of section headings."
    },
    "h5": {
        "detail": "Heading level 5",
        "insert": "h5>$1</h5>",
        "doc": "Represents the fifth level of section headings."
    },
    "h6": {
        "detail": "Heading level 6",
        "insert": "h6>$1</h6>",
        "doc": "Represents the sixth level of section headings."
    },
    "head": {
        "detail": "Document head",
        "insert": "head>\n  $1\n</head>",
        "doc": "Contains machine-readable information (metadata) about the document."
    },
    "header": {
        "detail": "Header section",
        "insert": "header>\n  $1\n</header>",
        "doc": "Represents introductory content, typically a group of introductory or navigational aids."
    },
    "hgroup": {
        "detail": "Heading group",
        "insert": "hgroup>\n  <h1>$1</h1>\n  <p>$2</p>\n</hgroup>",
        "doc": "Represents a heading and related content."
    },
    "hr": {
        "detail": "Thematic break",
        "insert": "hr>",
        "doc": "Represents a thematic break between paragraph-level elements.",
        "void": True
    },
    "html": {
        "detail": "HTML document root",
        "insert": "html lang=\"en\">\n  <head>\n    $1\n  </head>\n  <body>\n    $2\n  </body>\n</html>",
        "doc": "Represents the root (top-level element) of an HTML document."
    },
    "i": {
        "detail": "Italic text",
        "insert": "i>$1</i>",
        "doc": "Represents a range of text that is set off from the normal text for some reason."
    },
    "iframe": {
        "detail": "Inline frame",
        "insert": "iframe src=\"$1\" width=\"$2\" height=\"$3\"></iframe>",
        "doc": "Represents a nested browsing context, embedding another HTML page into the current one."
    },
    "img": {
        "detail": "Image",
        "insert": "img src=\"$1\" alt=\"$2\">",
        "doc": "Embeds an image into the document.",
        "void": True
    },
    "input": {
        "detail": "Form input",
        "insert": "input type=\"$1\" name=\"$2\">",
        "doc": "Used to create interactive controls for web-based forms.",
        "void": True
    },
    "ins": {
        "detail": "Inserted text",
        "insert": "ins>$1</ins>",
        "doc": "Represents a range of text that has been added to a document."
    },
    "kbd": {
        "detail": "Keyboard input",
        "insert": "kbd>$1</kbd>",
        "doc": "Represents a span of inline text denoting textual user input from a keyboard."
    },
    "label": {
        "detail": "Caption for form item",
        "insert": "label for=\"$1\">$2</label>",
        "doc": "Represents a caption for an item in a user interface."
    },
    "legend": {
        "detail": "Field set legend",
        "insert": "legend>$1</legend>",
        "doc": "Represents a caption for the content of its parent fieldset."
    },
    "li": {
        "detail": "List item",
        "insert": "li>$1</li>",
        "doc": "Represents an item in a list."
    },
    "link": {
        "detail": "External resource link",
        "insert": "link rel=\"$1\" href=\"$2\">",
        "doc": "Specifies relationships between the current document and an external resource.",
        "void": True
    },
    "main": {
        "detail": "Main content",
        "insert": "main>\n  $1\n</main>",
        "doc": "Represents the dominant content of the body of a document."
    },
    "map": {
        "detail": "Image map",
        "insert": "map name=\"$1\">\n  <area shape=\"$2\" coords=\"$3\" href=\"$4\">\n</map>",
        "doc": "Used with area elements to define an image map (a clickable link area)."
    },
    "mark": {
        "detail": "Marked text",
        "insert": "mark>$1</mark>",
        "doc": "Represents text which is marked or highlighted for reference or notation purposes."
    },
    "math": {
        "detail": "MathML",
        "insert": "math>\n  $1\n</math>",
        "doc": "The top-level element in MathML."
    },
    "menu": {
        "detail": "Menu",
        "insert": "menu>\n  <li>$1</li>\n</menu>",
        "doc": "A semantic alternative to ul."
    },
    "meta": {
        "detail": "Metadata",
        "insert": "meta name=\"$1\" content=\"$2\">",
        "doc": "Represents metadata that cannot be represented by other HTML meta-related elements.",
        "void": True
    },
    "meter": {
        "detail": "Scalar measurement",
        "insert": "meter value=\"$1\" min=\"$2\" max=\"$3\"></meter>",
        "doc": "Represents either a scalar value within a known range or a fractional value."
    },
    "nav": {
        "detail": "Navigation section",
        "insert": "nav>\n  $1\n</nav>",
        "doc": "Represents a section of a page whose purpose is to provide navigation links."
    },
    "noscript": {
        "detail": "Fallback for scripts",
        "insert": "noscript>\n  $1\n</noscript>",
        "doc": "Defines a section of HTML to be inserted if a script type on the page is unsupported."
    },
    "object": {
        "detail": "External object",
        "insert": "object data=\"$1\" type=\"$2\">\n  $3\n</object>",
        "doc": "Represents an external resource, which can be treated as an image, a nested browsing context, or a resource to be handled by a plugin."
    },
    "ol": {
        "detail": "Ordered list",
        "insert": "ol>\n  <li>$1</li>\n</ol>",
        "doc": "Represents an ordered list of items."
    },
    "optgroup": {
        "detail": "Option group",
        "insert": "optgroup label=\"$1\">\n  <option>$2</option>\n</optgroup>",
        "doc": "Creates a grouping of options within a select element."
    },
    "option": {
        "detail": "Option",
        "insert": "option value=\"$1\">$2</option>",
        "doc": "Used to define an item contained in a select, an optgroup, or a datalist element."
    },
    "output": {
        "detail": "Calculation result",
        "insert": "output for=\"$1\" name=\"$2\"></output>",
        "doc": "A container element into which a site or app can inject the results of a calculation."
    },
    "p": {
        "detail": "Paragraph",
        "insert": "p>$1</p>",
        "doc": "Represents a paragraph."
    },
    "param": {
        "detail": "Object parameter",
        "insert": "param name=\"$1\" value=\"$2\">",
        "doc": "Defines parameters for an object element.",
        "void": True
    },
    "picture": {
        "detail": "Picture container",
        "insert": "picture>\n  <source srcset=\"$1\" media=\"$2\">\n  <img src=\"$3\" alt=\"$4\">\n</picture>",
        "doc": "Contains zero or more source elements and one img element to offer alternative versions of an image."
    },
    "pre": {
        "detail": "Preformatted text",
        "insert": "pre>$1</pre>",
        "doc": "Represents preformatted text which is to be presented exactly as written in the HTML file."
    },
    "progress": {
        "detail": "Progress indicator",
        "insert": "progress value=\"$1\" max=\"$2\"></progress>",
        "doc": "Displays an indicator showing the completion progress of a task."
    },
    "q": {
        "detail": "Inline quotation",
        "insert": "q cite=\"$1\">$2</q>",
        "doc": "Indicates that the enclosed text is a short inline quotation."
    },
    "rp": {
        "detail": "Ruby fallback",
        "insert": "rp>($1)</rp>",
        "doc": "Used to provide fall-back parentheses for browsers that do not support display of ruby annotations."
    },
    "rt": {
        "detail": "Ruby text",
        "insert": "rt>$1</rt>",
        "doc": "Specifies the ruby text component of a ruby annotation."
    },
    "ruby": {
        "detail": "Ruby annotation",
        "insert": "ruby>\n  $1 <rt>$2</rt>\n</ruby>",
        "doc": "Represents small annotations that are rendered above, below, or next to base text."
    },
    "s": {
        "detail": "Strikethrough",
        "insert": "s>$1</s>",
        "doc": "Renders text with a strikethrough, or a line through it."
    },
    "samp": {
        "detail": "Sample output",
        "insert": "samp>$1</samp>",
        "doc": "Used to enclose inline text which represents sample (or quoted) output from a computer program."
    },
    "script": {
        "detail": "Script",
        "insert": "script>\n  $1\n</script>",
        "doc": "Used to embed executable code or data; this is typically used to embed or refer to JavaScript code."
    },
    "search": {
        "detail": "Search section",
        "insert": "search>\n  $1\n</search>",
        "doc": "Represents a part that contains a set of form controls or other content related to performing a search."
    },
    "section": {
        "detail": "Generic section",
        "insert": "section>\n  $1\n</section>",
        "doc": "Represents a generic standalone section of a document."
    },
    "select": {
        "detail": "Option selection control",
        "insert": "select name=\"$1\">\n  <option value=\"$2\">$3</option>\n</select>",
        "doc": "Represents a control that provides a menu of options."
    },
    "slot": {
        "detail": "Shadow DOM slot",
        "insert": "slot name=\"$1\"></slot>",
        "doc": "Part of the Web Components technology suite, this element is a placeholder inside a web component."
    },
    "small": {
        "detail": "Side comments",
        "insert": "small>$1</small>",
        "doc": "Represents side-comments and small print, like copyright and legal text."
    },
    "source": {
        "detail": "Media source",
        "insert": "source src=\"$1\" type=\"$2\">",
        "doc": "Specifies multiple media resources for the picture, the audio element, or the video element.",
        "void": True
    },
    "span": {
        "detail": "Generic span",
        "insert": "span>$1</span>",
        "doc": "A generic inline container for phrasing content."
    },
    "strong": {
        "detail": "Strong importance",
        "insert": "strong>$1</strong>",
        "doc": "Indicates that its contents have strong importance, seriousness, or urgency."
    },
    "style": {
        "detail": "Style information",
        "insert": "style>\n  $1\n</style>",
        "doc": "Contains style information for a document, or part of a document."
    },
    "sub": {
        "detail": "Subscript",
        "insert": "sub>$1</sub>",
        "doc": "Specifies inline text which should be displayed as subscript."
    },
    "summary": {
        "detail": "Details summary",
        "insert": "summary>$1</summary>",
        "doc": "Specifies a summary, caption, or legend for a details element's disclosure box."
    },
    "sup": {
        "detail": "Superscript",
        "insert": "sup>$1</sup>",
        "doc": "Specifies inline text which is to be displayed as superscript."
    },
    "svg": {
        "detail": "SVG container",
        "insert": "svg width=\"$1\" height=\"$2\" viewBox=\"0 0 $1 $2\">\n  $3\n</svg>",
        "doc": "Defines a container for SVG graphics."
    },
    "table": {
        "detail": "Table",
        "insert": "table>\n  <tr>\n    <th>$1</th>\n  </tr>\n  <tr>\n    <td>$2</td>\n  </tr>\n</table>",
        "doc": "Represents tabular data — that is, information presented in a two-dimensional table."
    },
    "tbody": {
        "detail": "Table body",
        "insert": "tbody>\n  <tr>\n    <td>$1</td>\n  </tr>\n</tbody>",
        "doc": "Encapsulates a set of table rows (tr elements), indicating that they comprise the body of the table (table)."
    },
    "td": {
        "detail": "Table cell",
        "insert": "td>$1</td>",
        "doc": "Defines a cell of a table that contains data."
    },
    "template": {
        "detail": "Content template",
        "insert": "template id=\"$1\">\n  $2\n</template>",
        "doc": "A mechanism for holding HTML that is not to be rendered immediately when a page is loaded."
    },
    "textarea": {
        "detail": "Multi-line text input",
        "insert": "textarea name=\"$1\" rows=\"$2\" cols=\"$3\"></textarea>",
        "doc": "Represents a multi-line plain-text editing control."
    },
    "tfoot": {
        "detail": "Table foot",
        "insert": "tfoot>\n  <tr>\n    <td>$1</td>\n  </tr>\n</tfoot>",
        "doc": "Defines a set of rows summarizing the columns of the table."
    },
    "th": {
        "detail": "Table header cell",
        "insert": "th>$1</th>",
        "doc": "Defines a cell as header of a group of table cells."
    },
    "thead": {
        "detail": "Table head",
        "insert": "thead>\n  <tr>\n    <th>$1</th>\n  </tr>\n</thead>",
        "doc": "Defines a set of rows defining the head of the columns of the table."
    },
    "time": {
        "detail": "Date/time",
        "insert": "time datetime=\"$1\">$2</time>",
        "doc": "Represents a specific period in time."
    },
    "title": {
        "detail": "Document title",
        "insert": "title>$1</title>",
        "doc": "Defines the document's title that is shown in a browser's title bar or a page's tab."
    },
    "tr": {
        "detail": "Table row",
        "insert": "tr>\n  <td>$1</td>\n</tr>",
        "doc": "Defines a row of cells in a table."
    },
    "track": {
        "detail": "Text track",
        "insert": "track kind=\"$1\" src=\"$2\" srclang=\"$3\">",
        "doc": "Used as a child of the media elements, audio and video.",
        "void": True
    },
    "u": {
        "detail": "Unarticulated annotation",
        "insert": "u>$1</u>",
        "doc": "Represents a span of inline text which should be rendered in a way that indicates that it has a non-textual annotation."
    },
    "ul": {
        "detail": "Unordered list",
        "insert": "ul>\n  <li>$1</li>\n</ul>",
        "doc": "Represents an unordered list of items."
    },
    "var": {
        "detail": "Variable",
        "insert": "var>$1</var>",
        "doc": "Represents the name of a variable in a mathematical expression or a programming context."
    },
    "video": {
        "detail": "Video player",
        "insert": "video controls width=\"$1\" height=\"$2\">\n  <source src=\"$3\" type=\"video/$4\">\n</video>",
        "doc": "Embeds a media player which supports video playback into the document."
    },
    "wbr": {
        "detail": "Line break opportunity",
        "insert": "wbr>",
        "doc": "Represents a word break opportunity—a position within text where the browser may optionally break a line.",
        "void": True
    }
}


# HTML Attributes
HTML_ATTRIBUTES: Dict[str, List[Dict]] = {
    "global": [
        {"name": "accesskey", "detail": "Keyboard shortcut", "doc": "Provides a hint for generating a keyboard shortcut for the current element."},
        {"name": "autocapitalize", "detail": "Auto-capitalization", "doc": "Controls whether and how text input is automatically capitalized."},
        {"name": "autofocus", "detail": "Auto-focus", "doc": "Indicates that an element should be focused on page load."},
        {"name": "class", "detail": "CSS class(es)", "doc": "A space-separated list of the classes of the element."},
        {"name": "contenteditable", "detail": "Editable content", "doc": "Indicates whether the element's content is editable."},
        {"name": "data-*", "detail": "Custom data attribute", "doc": "Forms a class of attributes called custom data attributes."},
        {"name": "dir", "detail": "Text direction", "doc": "An enumerated attribute indicating the directionality of the element's text."},
        {"name": "draggable", "detail": "Draggable", "doc": "An enumerated attribute indicating whether the element can be dragged."},
        {"name": "enterkeyhint", "detail": "Enter key hint", "doc": "Defines what action label (or icon) to present for the enter key on virtual keyboards."},
        {"name": "hidden", "detail": "Hidden", "doc": "Indicates that the element is not yet, or is no longer, relevant."},
        {"name": "id", "detail": "Unique identifier", "doc": "Defines a unique identifier (ID) which must be unique in the whole document."},
        {"name": "inert", "detail": "Inert", "doc": "Indicates that the browser will ignore the element."},
        {"name": "inputmode", "detail": "Input mode", "doc": "Hints at the type of data that might be entered by the user while editing the element."},
        {"name": "is", "detail": "Custom element type", "doc": "Allows you to specify that a standard HTML element should behave like a registered custom element."},
        {"name": "itemid", "detail": "Microdata item ID", "doc": "The unique, global identifier of an item."},
        {"name": "itemprop", "detail": "Microdata property", "doc": "Used to add properties to an item."},
        {"name": "itemref", "detail": "Microdata reference", "doc": "Properties that are not descendants of the element with the itemscope attribute."},
        {"name": "itemscope", "detail": "Microdata scope", "doc": "Creates an item and defines the scope of its associated metadata."},
        {"name": "itemtype", "detail": "Microdata type", "doc": "Specifies the URL of the vocabulary that will be used to define item properties."},
        {"name": "lang", "detail": "Language", "doc": "Helps define the language of an element."},
        {"name": "nonce", "detail": "Cryptographic nonce", "doc": "A cryptographic nonce used to allow inline styles and scripts."},
        {"name": "part", "detail": "CSS part", "doc": "A space-separated list of the part names of the element."},
        {"name": "popover", "detail": "Popover", "doc": "Designates an element as a popover element."},
        {"name": "role", "detail": "ARIA role", "doc": "Defines an explicit role for an element for use by assistive technologies."},
        {"name": "slot", "detail": "Shadow DOM slot", "doc": "Assigns a slot in a shadow DOM shadow tree to an element."},
        {"name": "spellcheck", "detail": "Spell check", "doc": "Enumerated attribute defines whether the element may be checked for spelling errors."},
        {"name": "style", "detail": "Inline CSS", "doc": "Contains CSS styling declarations to be applied to the element."},
        {"name": "tabindex", "detail": "Tab index", "doc": "Allows developers to make HTML elements focusable and define their navigation order."},
        {"name": "title", "detail": "Advisory title", "doc": "Contains text representing advisory information related to the element."},
        {"name": "translate", "detail": "Translation", "doc": "Enumerated attribute that is used to specify whether an element's attribute values and text content should be translated."},
        {"name": "virtualkeyboardpolicy", "detail": "Virtual keyboard policy", "doc": "An enumerated attribute used to control the on-screen virtual keyboard behavior."},
        # ARIA attributes
        {"name": "aria-atomic", "detail": "ARIA atomic", "doc": "Indicates whether assistive technologies will present all, or only parts of, the changed region."},
        {"name": "aria-busy", "detail": "ARIA busy", "doc": "Indicates an element is being modified."},
        {"name": "aria-controls", "detail": "ARIA controls", "doc": "Identifies the element (or elements) whose contents or presence are controlled by the current element."},
        {"name": "aria-current", "detail": "ARIA current", "doc": "Indicates the element that represents the current item within a container or set of related elements."},
        {"name": "aria-describedby", "detail": "ARIA described by", "doc": "Identifies the element (or elements) that describes the object."},
        {"name": "aria-details", "detail": "ARIA details", "doc": "Identifies the element that provides a detailed, extended description for the object."},
        {"name": "aria-disabled", "detail": "ARIA disabled", "doc": "Indicates that the element is perceivable but disabled."},
        {"name": "aria-dropeffect", "detail": "ARIA drop effect", "doc": "Indicates what functions can be performed when a dragged object is released on the drop target."},
        {"name": "aria-errormessage", "detail": "ARIA error message", "doc": "Identifies the element that provides an error message for an object."},
        {"name": "aria-expanded", "detail": "ARIA expanded", "doc": "Indicates whether the element, or another grouping element it controls, is currently expanded or collapsed."},
        {"name": "aria-flowto", "detail": "ARIA flow to", "doc": "Identifies the next element (or elements) in an alternate reading order of content."},
        {"name": "aria-grabbed", "detail": "ARIA grabbed", "doc": "Indicates an element's 'grabbed' state in a drag-and-drop operation."},
        {"name": "aria-haspopup", "detail": "ARIA has popup", "doc": "Indicates the availability and type of interactive popup element."},
        {"name": "aria-hidden", "detail": "ARIA hidden", "doc": "Indicates whether the element is exposed to an accessibility API."},
        {"name": "aria-invalid", "detail": "ARIA invalid", "doc": "Indicates the entered value does not conform to the format expected by the application."},
        {"name": "aria-keyshortcuts", "detail": "ARIA key shortcuts", "doc": "Indicates keyboard shortcuts that an author has implemented to activate or give focus to an element."},
        {"name": "aria-label", "detail": "ARIA label", "doc": "Defines a string value that labels the current element."},
        {"name": "aria-labelledby", "detail": "ARIA labelled by", "doc": "Identifies the element (or elements) that labels the current element."},
        {"name": "aria-live", "detail": "ARIA live", "doc": "Indicates that an element will be updated, and describes the types of updates."},
        {"name": "aria-modal", "detail": "ARIA modal", "doc": "Indicates whether an element is modal when displayed."},
        {"name": "aria-multiline", "detail": "ARIA multiline", "doc": "Indicates whether a text box accepts multiple lines of input or only a single line."},
        {"name": "aria-multiselectable", "detail": "ARIA multiselectable", "doc": "Indicates that the user may select more than one item from the current selectable descendants."},
        {"name": "aria-orientation", "detail": "ARIA orientation", "doc": "Indicates whether the element and orientation is horizontal or vertical."},
        {"name": "aria-owns", "detail": "ARIA owns", "doc": "Identifies an element (or elements) in order to define a visual, functional, or contextual parent/child relationship."},
        {"name": "aria-placeholder", "detail": "ARIA placeholder", "doc": "Defines a short hint (a word or short phrase) intended to aid the user with data entry."},
        {"name": "aria-posinset", "detail": "ARIA position in set", "doc": "Defines an element's number or position in the current set of listitems or treeitems."},
        {"name": "aria-pressed", "detail": "ARIA pressed", "doc": "Indicates the current 'pressed' state of toggle buttons."},
        {"name": "aria-readonly", "detail": "ARIA readonly", "doc": "Indicates that the element is not editable, but is otherwise operable."},
        {"name": "aria-relevant", "detail": "ARIA relevant", "doc": "Indicates what notifications the user agent will trigger when the accessibility tree within a live region is modified."},
        {"name": "aria-required", "detail": "ARIA required", "doc": "Indicates that user input is required on the element before a form may be submitted."},
        {"name": "aria-roledescription", "detail": "ARIA role description", "doc": "Defines a human-readable, author-localized description for the role of an element."},
        {"name": "aria-selected", "detail": "ARIA selected", "doc": "Indicates the current 'selected' state of various widgets."},
        {"name": "aria-setsize", "detail": "ARIA set size", "doc": "Defines the number of items in the current set of listitems or treeitems."},
        {"name": "aria-sort", "detail": "ARIA sort", "doc": "Indicates if items in a table or grid are sorted in ascending or descending order."},
        {"name": "aria-valuemax", "detail": "ARIA value max", "doc": "Defines the maximum allowed value for a range widget."},
        {"name": "aria-valuemin", "detail": "ARIA value min", "doc": "Defines the minimum allowed value for a range widget."},
        {"name": "aria-valuenow", "detail": "ARIA value now", "doc": "Defines the current value for a range widget."},
        {"name": "aria-valuetext", "detail": "ARIA value text", "doc": "Defines the human readable text alternative of aria-valuenow for a range widget."}
    ],
    "a": [
        {"name": "href", "detail": "URL", "doc": "The URL that the hyperlink points to."},
        {"name": "target", "detail": "Target context", "doc": "Where to display the linked URL."},
        {"name": "download", "detail": "Download filename", "doc": "Causes the browser to treat the linked URL as a download."},
        {"name": "ping", "detail": "Ping URLs", "doc": "URLs to ping when the link is followed."},
        {"name": "rel", "detail": "Relationship", "doc": "The relationship of the linked URL."},
        {"name": "hreflang", "detail": "Language", "doc": "Hints at the human language of the linked URL."},
        {"name": "type", "detail": "MIME type", "doc": "Hints at the linked URL's format with a MIME type."},
        {"name": "referrerpolicy", "detail": "Referrer policy", "doc": "How much referrer information to send."}
    ],
    "img": [
        {"name": "src", "detail": "Image URL", "doc": "The image URL."},
        {"name": "alt", "detail": "Alternative text", "doc": "Alternative text describing the image."},
        {"name": "width", "detail": "Width", "doc": "The intrinsic width of the image in pixels."},
        {"name": "height", "detail": "Height", "doc": "The intrinsic height of the image in pixels."},
        {"name": "loading", "detail": "Loading", "doc": "How the browser should load the image."},
        {"name": "decoding", "detail": "Decoding", "doc": "How the image should be decoded."},
        {"name": "crossorigin", "detail": "CORS", "doc": "Indicates if the image should be fetched with CORS."},
        {"name": "ismap", "detail": "Is map", "doc": "Whether the image is a server-side image map."},
        {"name": "usemap", "detail": "Use map", "doc": "The partial URL of an image map."}
    ],
    "input": [
        {"name": "type", "detail": "Input type", "doc": "The type of control to display."},
        {"name": "name", "detail": "Name", "doc": "The name of the input."},
        {"name": "value", "detail": "Value", "doc": "The initial value of the input."},
        {"name": "placeholder", "detail": "Placeholder", "doc": "A hint to the user of what can be entered."},
        {"name": "required", "detail": "Required", "doc": "Whether the input is required."},
        {"name": "disabled", "detail": "Disabled", "doc": "Whether the input is disabled."},
        {"name": "readonly", "detail": "Read-only", "doc": "Whether the input is read-only."},
        {"name": "checked", "detail": "Checked", "doc": "Whether the input is checked."},
        {"name": "multiple", "detail": "Multiple", "doc": "Whether multiple values are allowed."},
        {"name": "accept", "detail": "Accept", "doc": "Hint for expected file type in file upload controls."},
        {"name": "min", "detail": "Minimum", "doc": "Minimum value."},
        {"name": "max", "detail": "Maximum", "doc": "Maximum value."},
        {"name": "step", "detail": "Step", "doc": "Incremental values that are valid."},
        {"name": "pattern", "detail": "Pattern", "doc": "Pattern the value must match."},
        {"name": "minlength", "detail": "Min length", "doc": "Minimum length of the value."},
        {"name": "maxlength", "detail": "Max length", "doc": "Maximum length of the value."},
        {"name": "size", "detail": "Size", "doc": "Size of the control."},
        {"name": "autocomplete", "detail": "Auto-complete", "doc": "Hint for form autofill feature."},
        {"name": "autofocus", "detail": "Auto-focus", "doc": "Focus the form control when the page is loaded."},
        {"name": "form", "detail": "Form", "doc": "Associates the input with a form element."},
        {"name": "formaction", "detail": "Form action", "doc": "URL to use for form submission."},
        {"name": "formenctype", "detail": "Form encoding", "doc": "Form data set encoding type."},
        {"name": "formmethod", "detail": "Form method", "doc": "HTTP method to use for form submission."},
        {"name": "formnovalidate", "detail": "Form no validate", "doc": "Bypass form validation."},
        {"name": "formtarget", "detail": "Form target", "doc": "Browsing context for form submission."}
    ]
}


# Emmet abbreviations for HTML
EMMET_ABBREVIATIONS: Dict[str, str] = {
    "!": "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\">\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n  <title>Document</title>\n</head>\n<body>\n  \n</body>\n</html>",
    "html:5": "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"UTF-8\">\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n  <title>Document</title>\n</head>\n<body>\n  \n</body>\n</html>",
    "a": "<a href=\"\">",
    "a:link": "<a href=\"http://\">",
    "a:mail": "<a href=\"mailto:\">",
    "abbr": "<abbr title=\"\">",
    "address": "<address>",
    "area": "<area shape=\"\" coords=\"\" href=\"\">",
    "area:c": "<area shape=\"circle\" coords=\"\" href=\"\">",
    "area:r": "<area shape=\"rect\" coords=\"\" href=\"\">",
    "article": "<article>",
    "aside": "<aside>",
    "audio": "<audio src=\"\">",
    "b": "<b>",
    "base": "<base href=\"\">",
    "bdi": "<bdi>",
    "bdo": "<bdo dir=\"\">",
    "blockquote": "<blockquote>",
    "body": "<body>",
    "br": "<br>",
    "button": "<button type=\"button\">",
    "button:s": "<button type=\"submit\">",
    "button:r": "<button type=\"reset\">",
    "canvas": "<canvas>",
    "caption": "<caption>",
    "cite": "<cite>",
    "code": "<code>",
    "col": "<col>",
    "colgroup": "<colgroup>",
    "data": "<data value=\"\">",
    "datalist": "<datalist>",
    "dd": "<dd>",
    "del": "<del>",
    "details": "<details>",
    "dfn": "<dfn>",
    "dialog": "<dialog>",
    "div": "<div>",
    "dl": "<dl>",
    "dt": "<dt>",
    "em": "<em>",
    "embed": "<embed src=\"\" type=\"\">",
    "fieldset": "<fieldset>",
    "figcaption": "<figcaption>",
    "figure": "<figure>",
    "footer": "<footer>",
    "form": "<form action=\"\">",
    "form:get": "<form action=\"\" method=\"get\">",
    "form:post": "<form action=\"\" method=\"post\">",
    "h1": "<h1>",
    "h2": "<h2>",
    "h3": "<h3>",
    "h4": "<h4>",
    "h5": "<h5>",
    "h6": "<h6>",
    "head": "<head>",
    "header": "<header>",
    "hgroup": "<hgroup>",
    "hr": "<hr>",
    "html": "<html>",
    "i": "<i>",
    "iframe": "<iframe src=\"\">",
    "img": "<img src=\"\" alt=\"\">",
    "input": "<input type=\"text\">",
    "input:hidden": "<input type=\"hidden\" name=\"\">",
    "input:h": "<input type=\"hidden\" name=\"\">",
    "input:text": "<input type=\"text\" name=\"\" id=\"\">",
    "input:t": "<input type=\"text\" name=\"\" id=\"\">",
    "input:search": "<input type=\"search\" name=\"\" id=\"\">",
    "input:email": "<input type=\"email\" name=\"\" id=\"\">",
    "input:url": "<input type=\"url\" name=\"\" id=\"\">",
    "input:password": "<input type=\"password\" name=\"\" id=\"\">",
    "input:p": "<input type=\"password\" name=\"\" id=\"\">",
    "input:datetime": "<input type=\"datetime\" name=\"\" id=\"\">",
    "input:date": "<input type=\"date\" name=\"\" id=\"\">",
    "input:datetime-local": "<input type=\"datetime-local\" name=\"\" id=\"\">",
    "input:month": "<input type=\"month\" name=\"\" id=\"\">",
    "input:week": "<input type=\"week\" name=\"\" id=\"\">",
    "input:time": "<input type=\"time\" name=\"\" id=\"\">",
    "input:tel": "<input type=\"tel\" name=\"\" id=\"\">",
    "input:number": "<input type=\"number\" name=\"\" id=\"\">",
    "input:n": "<input type=\"number\" name=\"\" id=\"\">",
    "input:range": "<input type=\"range\" name=\"\" id=\"\">",
    "input:color": "<input type=\"color\" name=\"\" id=\"\">",
    "input:checkbox": "<input type=\"checkbox\" name=\"\" id=\"\">",
    "input:c": "<input type=\"checkbox\" name=\"\" id=\"\">",
    "input:radio": "<input type=\"radio\" name=\"\" id=\"\">",
    "input:r": "<input type=\"radio\" name=\"\" id=\"\">",
    "input:file": "<input type=\"file\" name=\"\" id=\"\">",
    "input:f": "<input type=\"file\" name=\"\" id=\"\">",
    "input:submit": "<input type=\"submit\" value=\"\">",
    "input:s": "<input type=\"submit\" value=\"\">",
    "input:image": "<input type=\"image\" src=\"\" alt=\"\">",
    "input:i": "<input type=\"image\" src=\"\" alt=\"\">",
    "input:button": "<input type=\"button\" value=\"\">",
    "input:b": "<input type=\"button\" value=\"\">",
    "input:reset": "<input type=\"reset\" value=\"\">",
    "ins": "<ins>",
    "kbd": "<kbd>",
    "label": "<label for=\"\">",
    "legend": "<legend>",
    "li": "<li>",
    "link": "<link rel=\"stylesheet\" href=\"\">",
    "link:css": "<link rel=\"stylesheet\" href=\"style.css\">",
    "link:favicon": "<link rel=\"shortcut icon\" type=\"image/x-icon\" href=\"favicon.ico\">",
    "main": "<main>",
    "map": "<map name=\"\">",
    "mark": "<mark>",
    "menu": "<menu>",
    "meta": "<meta>",
    "meta:utf": "<meta charset=\"UTF-8\">",
    "meta:vp": "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">",
    "meter": "<meter>",
    "nav": "<nav>",
    "noscript": "<noscript>",
    "object": "<object data=\"\">",
    "ol": "<ol>",
    "optgroup": "<optgroup>",
    "option": "<option value=\"\">",
    "output": "<output>",
    "p": "<p>",
    "param": "<param name=\"\" value=\"\">",
    "picture": "<picture>",
    "pre": "<pre>",
    "progress": "<progress>",
    "q": "<q>",
    "rp": "<rp>",
    "rt": "<rt>",
    "ruby": "<ruby>",
    "s": "<s>",
    "samp": "<samp>",
    "script": "<script>",
    "script:src": "<script src=\"\">",
    "section": "<section>",
    "select": "<select name=\"\" id=\"\">",
    "small": "<small>",
    "source": "<source src=\"\" type=\"\">",
    "source:srcset": "<source srcset=\"\" type=\"\">",
    "span": "<span>",
    "strong": "<strong>",
    "style": "<style>",
    "sub": "<sub>",
    "summary": "<summary>",
    "sup": "<sup>",
    "svg": "<svg>",
    "table": "<table>",
    "tbody": "<tbody>",
    "td": "<td>",
    "template": "<template>",
    "textarea": "<textarea name=\"\" id=\"\" cols=\"30\" rows=\"10\"></textarea>",
    "tfoot": "<tfoot>",
    "th": "<th>",
    "thead": "<thead>",
    "time": "<time datetime=\"\">",
    "title": "<title>",
    "tr": "<tr>",
    "track": "<track src=\"\">",
    "u": "<u>",
    "ul": "<ul>",
    "var": "<var>",
    "video": "<video src=\"\">",
    "wbr": "<wbr>"
}


class HTMLCompletionProvider:
    """Provides HTML IntelliSense completions."""
    
    def __init__(self):
        self.tags = HTML_TAGS
        self.attributes = HTML_ATTRIBUTES
        self.emmet = EMMET_ABBREVIATIONS
    
    def get_completions(self, content: str, line: int, column: int) -> List[HTMLCompletionItem]:
        """Get completions based on cursor position."""
        lines = content.split('\n')
        if line >= len(lines):
            return []
        
        current_line = lines[line]
        text_before = current_line[:column]
        
        # Determine context
        context = self._get_context(content, line, column, text_before)
        
        if context == "tag":
            return self._get_tag_completions(text_before)
        elif context == "attribute":
            return self._get_attribute_completions(content, line, column)
        elif context == "attribute_value":
            return self._get_value_completions(content, line, column)
        elif context == "emmet":
            return self._get_emmet_completions(text_before)
        else:
            # Default to tag completions
            return self._get_tag_completions(text_before)
    
    def _get_context(self, content: str, line: int, column: int, text_before: str) -> str:
        """Determine the completion context."""
        # Check if inside a tag
        tag_start = text_before.rfind('<')
        tag_end = text_before.rfind('>')
        
        if tag_start > tag_end:
            # Inside a tag
            tag_content = text_before[tag_start + 1:]
            
            # Check if typing attribute value
            if '=' in tag_content:
                quote_match = re.search(r'=\s*["\'][^"\']*$', text_before)
                if quote_match:
                    return "attribute_value"
            
            # Check if after tag name
            space_match = re.search(r'\s', tag_content)
            if space_match:
                return "attribute"
            
            return "tag"
        
        # Check for Emmet abbreviation (simple word before cursor)
        word_match = re.search(r'(\w+)$', text_before.strip())
        if word_match:
            word = word_match.group(1)
            if word in self.emmet or len(word) >= 2:
                return "emmet"
        
        return "tag"
    
    def _get_tag_completions(self, text_before: str) -> List[HTMLCompletionItem]:
        """Get tag completions."""
        completions = []
        
        # Get partial tag name if any
        match = re.search(r'<(\w*)$', text_before)
        prefix = match.group(1) if match else ""
        
        for tag_name, info in self.tags.items():
            if prefix and not tag_name.startswith(prefix.lower()):
                continue
            
            insert = info.get("insert", f"{tag_name}>$1</{tag_name}>")
            if not insert.startswith("<"):
                insert = f"<{insert}"
            
            completions.append(HTMLCompletionItem(
                label=tag_name,
                kind="tag",
                detail=info.get("detail", f"HTML {tag_name} element"),
                insert_text=insert,
                documentation=info.get("doc", ""),
                sort_text=f"a{tag_name}"
            ))
        
        return completions
    
    def _get_attribute_completions(self, content: str, line: int, column: int) -> List[HTMLCompletionItem]:
        """Get attribute completions for current tag."""
        completions = []
        
        # Find current tag
        lines = content.split('\n')
        current_line = lines[line][:column]
        tag_match = re.search(r'<(\w+)[^>]*$', current_line)
        
        if tag_match:
            tag_name = tag_match.group(1).lower()
            tag_attrs = self.attributes.get(tag_name, [])
            global_attrs = self.attributes.get("global", [])
            
            for attr in tag_attrs + global_attrs:
                completions.append(HTMLCompletionItem(
                    label=attr["name"],
                    kind="attribute",
                    detail=attr.get("detail", ""),
                    insert_text=f'{attr["name"]}="$1"',
                    documentation=attr.get("doc", ""),
                    sort_text=f'b{attr["name"]}'
                ))
        
        return completions
    
    def _get_value_completions(self, content: str, line: int, column: int) -> List[HTMLCompletionItem]:
        """Get attribute value completions."""
        # This would need more context about the attribute
        # For now, return empty
        return []
    
    def _get_emmet_completions(self, text_before: str) -> List[HTMLCompletionItem]:
        """Get Emmet abbreviation completions."""
        completions = []
        
        # Get word before cursor
        match = re.search(r'(\w+)$', text_before.strip())
        if not match:
            return completions
        
        prefix = match.group(1)
        
        for abbrev, expansion in self.emmet.items():
            if abbrev.startswith(prefix) or prefix in abbrev:
                completions.append(HTMLCompletionItem(
                    label=abbrev,
                    kind="emmet",
                    detail="Emmet abbreviation",
                    insert_text=expansion,
                    documentation=f"Expands to: {expansion[:50]}...",
                    sort_text=f'c{abbrev}'
                ))
        
        return completions
    
    def expand_emmet(self, abbreviation: str) -> Optional[str]:
        """Expand an Emmet abbreviation to HTML."""
        return self.emmet.get(abbreviation)


def get_closing_tag(text_before: str) -> Optional[str]:
    """
    Check if we need to auto-close a tag.
    
    Returns the closing tag if needed, None otherwise.
    Example: '<html>' -> '</html>'
             '<br>' -> None (void tag)
             '<img src="x">' -> None (void tag)
    """
    # Find the last opening tag
    match = re.search(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*>$', text_before)
    if not match:
        return None
    
    tag_name = match.group(1).lower()
    
    # Don't close void tags
    if tag_name in VOID_TAGS:
        return None
    
    # Don't close if it's already a closing tag
    if text_before.rstrip().endswith(f'</{tag_name}>'):
        return None
    
    # Don't close if there's already a matching closing tag
    # Simple check: count opening and closing tags
    open_count = len(re.findall(rf'<{tag_name}[\s>]', text_before, re.IGNORECASE))
    close_count = len(re.findall(rf'</{tag_name}>', text_before, re.IGNORECASE))
    
    if open_count <= close_count:
        return None
    
    return f"</{tag_name}>"


# Singleton instance
_html_completion_provider: Optional[HTMLCompletionProvider] = None


def get_html_completion_provider() -> HTMLCompletionProvider:
    """Get the singleton HTML completion provider."""
    global _html_completion_provider
    if _html_completion_provider is None:
        _html_completion_provider = HTMLCompletionProvider()
    return _html_completion_provider
