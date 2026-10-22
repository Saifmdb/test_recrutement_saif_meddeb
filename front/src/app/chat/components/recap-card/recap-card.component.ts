import { Component, input, output } from '@angular/core';
import { Recap } from '../../../core/chat.models';

@Component({
  selector: 'app-recap-card',
  templateUrl: './recap-card.component.html',
  styleUrl: './recap-card.component.css',
})
export class RecapCardComponent {
  readonly recap = input.required<Recap>();
  /** Buttons are only shown on the latest recap of the conversation. */
  readonly showActions = input(false);
  readonly disabled = input(false);
  readonly confirm = output<void>();
  readonly edit = output<void>();
}
