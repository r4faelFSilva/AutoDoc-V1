import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

@Pipe({ name: 'highlight', standalone: true })
export class HighlightPipe implements PipeTransform {
  constructor(private sanitizer: DomSanitizer) {}

  transform(text: string, query: string): SafeHtml {
    if (!query || !text) return text;
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const highlighted = text.replace(
      new RegExp(escaped, 'gi'),
      match => `<mark class="search-highlight">${match}</mark>`,
    );
    return this.sanitizer.bypassSecurityTrustHtml(highlighted);
  }
}
