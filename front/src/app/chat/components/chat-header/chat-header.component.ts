import { Component, input, output } from '@angular/core';

@Component({
  selector: 'app-chat-header',
  templateUrl: './chat-header.component.html',
  styleUrl: './chat-header.component.css',
})
export class ChatHeaderComponent {
  readonly title = input('Nouvelle discussion');
  /** Mobile only: opens the sidebar. */
  readonly menu = output<void>();
}
