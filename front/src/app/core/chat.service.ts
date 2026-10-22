import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { ChatMessage, ChatResponse, ConversationSummary, HistoryResponse } from './chat.models';

const CURRENT_KEY = 'admissions.conversationId';
const LIST_KEY = 'admissions.conversations';
const MAX_RECENT = 20;

@Injectable({ providedIn: 'root' })
export class ChatService {
  private readonly http = inject(HttpClient);

  readonly messages = signal<ChatMessage[]>([]);
  readonly loading = signal(false);
  readonly conversations = signal<ConversationSummary[]>([]);
  readonly currentId = signal<string | null>(null);
  readonly currentTitle = computed(
    () => this.conversations().find((c) => c.id === this.currentId())?.title ?? 'Nouvelle discussion',
  );

  /** Restore the recent conversations and reopen the last one (after a page reload). */
  restore(): void {
    this.conversations.set(this.read<ConversationSummary[]>(LIST_KEY) ?? []);
    const id = this.read<string>(CURRENT_KEY);
    if (id) this.open(id);
  }

  open(id: string): void {
    if (this.loading()) return;
    this.currentId.set(id);
    this.write(CURRENT_KEY, id);
    this.messages.set([]);
    this.http.get<HistoryResponse>(`/api/chat/${id}/`).subscribe({
      next: (res) => this.messages.set(res.messages),
      error: () => {
        // Conversation no longer exists on the server: forget it
        this.conversations.update((list) => list.filter((c) => c.id !== id));
        this.write(LIST_KEY, this.conversations());
        this.newConversation();
      },
    });
  }

  newConversation(): void {
    this.currentId.set(null);
    this.messages.set([]);
    this.remove(CURRENT_KEY);
  }

  send(text: string): void {
    const message = text.trim();
    if (!message || this.loading()) return;
    this.messages.update((list) => [...list, { role: 'user', text: message }]);
    this.loading.set(true);

    this.http.post<ChatResponse>('/api/chat/', { conversation_id: this.currentId(), message }).subscribe({
      next: (res) => {
        this.remember(res.conversation_id, message);
        this.messages.update((list) => [...list, res.message]);
        this.loading.set(false);
      },
      error: () => {
        this.messages.update((list) => [
          ...list,
          {
            role: 'assistant',
            text: "Désolé, je n'arrive pas à joindre le serveur. Merci de réessayer dans un instant.",
            error: true,
          },
        ]);
        this.loading.set(false);
      },
    });
  }

  /** Add / move the conversation to the top of "Récent"; its title is the first question asked. */
  private remember(id: string, firstMessage: string): void {
    this.currentId.set(id);
    this.write(CURRENT_KEY, id);
    this.conversations.update((list) => {
      const existing = list.find((c) => c.id === id);
      const title = existing?.title ?? (firstMessage.length > 40 ? firstMessage.slice(0, 40).trim() + '…' : firstMessage);
      return [{ id, title }, ...list.filter((c) => c.id !== id)].slice(0, MAX_RECENT);
    });
    this.write(LIST_KEY, this.conversations());
  }

  // localStorage can be unavailable (private mode, blocked storage): never let it break the chat
  private read<T>(key: string): T | null {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : null;
    } catch {
      return null;
    }
  }

  private write(key: string, value: unknown): void {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {}
  }

  private remove(key: string): void {
    try {
      localStorage.removeItem(key);
    } catch {}
  }
}
