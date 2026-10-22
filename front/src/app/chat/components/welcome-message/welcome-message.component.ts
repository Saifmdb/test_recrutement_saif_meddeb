import { Component, input, output } from '@angular/core';

@Component({
  selector: 'app-welcome-message',
  templateUrl: './welcome-message.component.html',
  styleUrl: './welcome-message.component.css',
})
export class WelcomeMessageComponent {
  readonly showSuggestions = input(true);
  readonly pick = output<string>();

  protected readonly suggestions = [
    'Quels documents dois-je fournir pour déposer une candidature ?',
    'Quelles spécialités proposez-vous en informatique ?',
    "J'ai un bac informatique, quelles spécialités me correspondent ?",
    "Je veux m'inscrire",
  ];
}
