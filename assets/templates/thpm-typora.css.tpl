/* THPM Typora theme — generated from the active Omarchy semantic palette. */
:root {
  --bg-color: {{ background }};
  --side-bar-bg-color: {{ dark_background }};
  --text-color: {{ foreground }};
  --control-text-color: {{ muted }};
  --control-text-hover-color: {{ bright_foreground }};
  --select-text-bg-color: {{ selection }};
  --select-text-font-color: {{ bright_foreground }};
  --item-hover-bg-color: {{ lighter_background }};
  --item-hover-text-color: {{ bright_foreground }};
  --active-file-bg-color: {{ selection }};
  --active-file-text-color: {{ bright_foreground }};
  --active-file-border-color: {{ blue }};
  --primary-color: {{ blue }};
  --window-border: 1px solid {{ muted }};
  --rawblock-edit-panel-bd: {{ darker_background }};
  --search-select-bg-color: {{ selection }};
  --search-select-text-color: {{ bright_foreground }};
  --thpm-dark-bg: {{ dark_background }};
  --thpm-darker-bg: {{ darker_background }};
  --thpm-lighter-bg: {{ lighter_background }};
  --thpm-muted: {{ muted }};
  --thpm-dark-fg: {{ dark_foreground }};
  --thpm-bright-fg: {{ bright_foreground }};
  --thpm-red: {{ red }};
  --thpm-yellow: {{ yellow }};
  --thpm-orange: {{ orange }};
  --thpm-green: {{ green }};
  --thpm-cyan: {{ cyan }};
  --thpm-blue: {{ blue }};
  --thpm-magenta: {{ magenta }};
}

html,
body,
#write,
.content,
.typora-node {
  background: var(--bg-color);
  color: var(--text-color);
}

html,
body,
button,
input,
select,
textarea,
.context-menu,
.popover,
.modal-content {
  color: var(--text-color);
  border-color: var(--thpm-muted);
}

#write {
  max-width: 980px;
  line-height: 1.65;
}

h1,
h2,
h3,
h4,
h5,
h6 {
  color: var(--thpm-bright-fg);
}

h1,
h2 {
  border-bottom: 1px solid var(--thpm-lighter-bg);
}

a,
.md-inline-math script,
.md-toc-item {
  color: var(--thpm-blue);
}

a:hover {
  color: var(--thpm-cyan);
}

::selection,
.in-text-selection {
  background: var(--select-text-bg-color);
  color: var(--select-text-font-color);
}

blockquote {
  color: var(--thpm-muted);
  border-left: 4px solid var(--thpm-blue);
  background: var(--thpm-dark-bg);
  padding: 0.5em 1em;
}

hr {
  background: var(--thpm-lighter-bg);
  height: 2px;
  border: 0;
}

code,
tt,
var,
kbd,
.md-fences,
pre.md-meta-block,
.md-inline-code {
  background: var(--thpm-darker-bg);
  color: var(--thpm-bright-fg);
}

pre.md-fences {
  border: 1px solid var(--thpm-lighter-bg);
  border-radius: 5px;
}

.CodeMirror,
.CodeMirror-gutters,
.CodeMirror-scroll,
.CodeMirror-code {
  background: var(--thpm-darker-bg);
  color: var(--text-color);
}

.CodeMirror-gutters {
  border-right: 1px solid var(--thpm-lighter-bg);
}

.cm-s-inner .cm-comment { color: var(--thpm-muted); }
.cm-s-inner .cm-keyword,
.cm-s-inner .cm-operator { color: var(--thpm-magenta); }
.cm-s-inner .cm-string,
.cm-s-inner .cm-string-2 { color: var(--thpm-green); }
.cm-s-inner .cm-number,
.cm-s-inner .cm-atom { color: var(--thpm-orange); }
.cm-s-inner .cm-def,
.cm-s-inner .cm-variable-2,
.cm-s-inner .cm-variable-3 { color: var(--thpm-cyan); }
.cm-s-inner .cm-property,
.cm-s-inner .cm-attribute { color: var(--thpm-blue); }
.cm-s-inner .cm-error { color: var(--thpm-red); }

mark {
  background: var(--thpm-yellow);
  color: var(--thpm-darker-bg);
}

th,
td {
  border: 1px solid var(--thpm-lighter-bg);
  padding: 0.45em 0.75em;
}

th {
  background: var(--thpm-dark-bg);
  color: var(--thpm-bright-fg);
}

tr:nth-child(2n) {
  background: var(--thpm-darker-bg);
}

.md-task-list-item > input:before {
  background: var(--bg-color);
  border: 1px solid var(--thpm-muted);
}

.md-task-list-item > input:checked:before,
.md-task-list-item > input[checked]:before {
  background: var(--thpm-green);
  border-color: var(--thpm-green);
  color: var(--thpm-darker-bg);
}

#typora-sidebar,
.sidebar-content,
.sidebar-tabs,
.sidebar-footer,
#file-library,
#file-library-list {
  background: var(--side-bar-bg-color);
  color: var(--control-text-color);
  border-color: var(--thpm-lighter-bg);
}

.file-library-node.active > .file-node-background,
.file-list-item.active,
.active-tab-files #info-panel-tab-file,
.active-tab-outline #info-panel-tab-outline {
  background: var(--active-file-bg-color);
  color: var(--active-file-text-color);
}

.file-library-node.active > .file-node-content,
.file-list-item.active {
  border-left-color: var(--active-file-border-color);
}

.file-library-node:hover > .file-node-background,
.file-list-item:hover,
.outline-item:hover,
.sidebar-footer-item:hover,
.footer-item:hover,
.nav-group-item:hover {
  background: var(--item-hover-bg-color);
  color: var(--item-hover-text-color);
}

#top-titlebar,
#top-titlebar * ,
header,
.megamenu-opened header,
.megamenu-content,
.megamenu-menu-panel {
  background: var(--thpm-dark-bg);
  color: var(--text-color);
  border-color: var(--thpm-lighter-bg);
}

.context-menu,
.dropdown-menu,
#spell-check-panel,
#footer-word-count-info,
#toc-dropmenu,
.auto-suggest-container,
#typora-quick-open,
.modal-content,
.popover,
.ty-table-edit,
.md-table-resize-popover {
  background: var(--thpm-dark-bg);
  color: var(--text-color);
  border-color: var(--thpm-lighter-bg);
}

.context-menu .active,
.dropdown-menu > li > a:hover,
.dropdown-menu > li > a:focus,
.typora-quick-open-item.active,
.typora-quick-open-item:hover {
  background: var(--select-text-bg-color);
  color: var(--select-text-font-color);
}

input,
textarea,
select,
.modal-content input,
#typora-quick-open input,
#md-searchpanel input,
.ty-preferences input[type="search"] {
  background: var(--thpm-darker-bg);
  color: var(--text-color);
  border: 1px solid var(--thpm-lighter-bg);
}

.btn,
.btn-default,
.long-btn,
#recent-file-panel-action-btn {
  background: var(--thpm-dark-bg);
  color: var(--text-color);
  border-color: var(--thpm-muted);
}

.btn:hover,
.btn:focus,
.btn-primary,
#recent-file-panel-action-btn:hover {
  background: var(--thpm-blue);
  color: var(--thpm-bright-fg);
  border-color: var(--thpm-blue);
}

footer,
.ty-footer,
#md-searchpanel,
.ty-editor-toolbar {
  background: var(--thpm-dark-bg);
  color: var(--control-text-color);
  border-color: var(--thpm-lighter-bg);
}

#footer-word-count:hover,
.ty-show-word-count #footer-word-count,
#toggle-sourceview-btn:hover,
.typora-sourceview-on #toggle-sourceview-btn {
  background: var(--thpm-lighter-bg);
  color: var(--thpm-bright-fg);
}

.md-alert-text-note { color: var(--thpm-blue); }
.md-alert-text-important { color: var(--thpm-magenta); }
.md-alert-text-warning { color: var(--thpm-yellow); }
.md-diagram-panel-error,
.md-error { color: var(--thpm-red); }

::-webkit-scrollbar-thumb {
  background: var(--thpm-muted);
}

::-webkit-scrollbar-thumb:active {
  background: var(--thpm-blue);
}

/* Keep printed/exported documents neutral and ink-conscious. The Omarchy
   palette is a screen treatment, not document content. */
@media print {
  html,
  body,
  #write,
  .content,
  .typora-node {
    background: #fff !important;
    color: #000 !important;
  }

  #write *,
  #write *::before,
  #write *::after {
    background: transparent !important;
    color: #000 !important;
    text-shadow: none !important;
    box-shadow: none !important;
    border-color: #777 !important;
  }

  #write a,
  #write a:visited {
    color: #000 !important;
    text-decoration: underline !important;
  }

  #write blockquote,
  #write table,
  #write th,
  #write td,
  #write pre,
  #write code,
  #write kbd {
    border-color: #777 !important;
  }

  #typora-sidebar,
  #top-titlebar,
  header,
  footer,
  .ty-footer,
  .ty-editor-toolbar,
  #md-searchpanel,
  #typora-quick-open,
  .context-menu,
  .dropdown-menu,
  .popover,
  .modal-content {
    display: none !important;
  }
}
