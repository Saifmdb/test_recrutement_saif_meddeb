import { Component, input, output } from '@angular/core';
import { ConversationSummary } from '../../../core/chat.models';

@Component({
  selector: 'app-chat-sidebar',
  templateUrl: './chat-sidebar.component.html',
  styleUrl: './chat-sidebar.component.css',
  host: { '[class.open]': 'open()' },
})
export class ChatSidebarComponent {
  readonly conversations = input<ConversationSummary[]>([]);
  readonly currentId = input<string | null>(null);
  readonly disabled = input(false);
  /** Mobile only: the sidebar slides over the chat. */
  readonly open = input(false);

  readonly newConversation = output<void>();
  readonly select = output<string>();
  readonly close = output<void>();
}
