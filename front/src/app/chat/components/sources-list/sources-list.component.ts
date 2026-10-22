import { Component, input } from '@angular/core';
import { Source } from '../../../core/chat.models';

@Component({
  selector: 'app-sources-list',
  templateUrl: './sources-list.component.html',
  styleUrl: './sources-list.component.css',
})
export class SourcesListComponent {
  readonly sources = input.required<Source[]>();
}
