import { Component, input, output } from '@angular/core';
import { ChatMessage, Formation } from '../../../core/chat.models';
import { FormatTextPipe } from '../../../shared/format-text.pipe';
import { FormationCardComponent } from '../formation-card/formation-card.component';
import { RecapCardComponent } from '../recap-card/recap-card.component';
import { SourcesListComponent } from '../sources-list/sources-list.component';

@Component({
  selector: 'app-message',
  imports: [FormatTextPipe, FormationCardComponent, RecapCardComponent, SourcesListComponent],
  templateUrl: './message.component.html',
  styleUrl: './message.component.css',
})
export class MessageComponent {
  readonly message = input.required<ChatMessage>();
  readonly isLast = input(false);
  readonly disabled = input(false);
  /** Card / recap buttons are turned into a chat message sent on behalf of the prospect. */
  readonly send = output<string>();

  protected register(f: Formation): void {
    this.send.emit(`Je veux m'inscrire à la formation : ${f.diplome} — ${f.specialite} (${f.ecole})`);
  }

  protected checkEligibility(f: Formation): void {
    this.send.emit(`Suis-je éligible à la formation : ${f.diplome} — ${f.specialite} (${f.ecole}) ?`);
  }
}
