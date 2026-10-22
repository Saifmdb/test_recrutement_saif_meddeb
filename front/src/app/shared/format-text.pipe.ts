import { Pipe, PipeTransform } from '@angular/core';

/** Minimal, safe Markdown: escapes HTML, then supports **bold**, "- " bullet lists and line breaks. */
@Pipe({ name: 'formatText' })
export class FormatTextPipe implements PipeTransform {
  transform(value: string | null | undefined): string {
    if (!value) return '';
    const escaped = value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');

    const html: string[] = [];
    let inList = false;
    for (const rawLine of escaped.split('\n')) {
      const line = rawLine.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (bullet) {
        if (!inList) html.push('<ul>');
        inList = true;
        html.push(`<li>${bullet[1]}</li>`);
        continue;
      }
      if (inList) html.push('</ul>');
      inList = false;
      html.push(line.trim() ? `<p>${line}</p>` : '');
    }
    if (inList) html.push('</ul>');
    return html.join('');
  }
}
