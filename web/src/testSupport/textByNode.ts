/**
 * The text under `root`, one text node at a time, joined with a space.
 *
 * `textContent` joins neighbouring elements with nothing between them, so a badge reading
 * "live" followed by a note starting "Adı" reads "liveAdı", and a whole-word check such as
 * `/\blive\b/` cannot see the badge. Joining text node by text node puts a boundary at every
 * element edge, so a word check reads each label as the reader sees it. Hidden text (a
 * visually hidden caption) is included, as it is in `textContent`.
 */
export function textByNode(root: Node): string {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const parts: string[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode())
    parts.push(node.nodeValue ?? "");
  return parts.join(" ");
}
