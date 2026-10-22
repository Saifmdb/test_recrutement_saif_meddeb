import { Component, ElementRef, afterNextRender, effect, inject, signal, viewChild } from '@angular/core';
import { ChatService } from '../core/chat.service';
import { ChatHeaderComponent } from './components/chat-header/chat-header.component';
import { ChatInputComponent } from './components/chat-input/chat-input.component';
import { ChatSidebarComponent } from './components/chat-sidebar/chat-sidebar.component';
import { MessageComponent } from './components/message/message.component';
import { TypingIndicatorComponent } from './components/typing-indicator/typing-indicator.component';
import { WelcomeMessageComponent } from './components/welcome-message/welcome-message.component';

/** Chat page: assembles the components and connects them to ChatService. */
@Component({
  selector: 'app-chat',
  imports: [
    ChatSidebarComponent,
    ChatHeaderComponent,
    WelcomeMessageComponent,
    MessageComponent,
    TypingIndicatorComponent,
    ChatInputComponent,
  ],
  templateUrl: './chat.component.html',
  styleUrl: './chat.component.css',
})
export class ChatComponent {
  protected readonly chat = inject(ChatService);
  protected readonly sidebarOpen = signal(false);
  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');

  constructor() {
    afterNextRender(() => this.chat.restore());
    // Keep the latest message visible
    effect(() => {
      this.chat.messages();
      this.chat.loading();
      queueMicrotask(() => {
        const el = this.scroller()?.nativeElement;
        if (el) el.scrollTop = el.scrollHeight;
      });
    });
  }

  protected send(text: string): void {
    this.chat.send(text);
  }

  protected newConversation(): void {
    this.chat.newConversation();
    this.sidebarOpen.set(false);
  }

  protected open(id: string): void {
    this.chat.open(id);
    this.sidebarOpen.set(false);
  }
}
