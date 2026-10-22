import { Component, computed, input, output } from '@angular/core';
import { Formation } from '../../../core/chat.models';

@Component({
  selector: 'app-formation-card',
  templateUrl: './formation-card.component.html',
  styleUrl: './formation-card.component.css',
})
export class FormationCardComponent {
  readonly formation = input.required<Formation>();
  readonly disabled = input(false);
  readonly register = output<Formation>();
  readonly checkEligibility = output<Formation>();

  /** Excel values made readable: "All" = no restriction, "san bac" = bac not required. */
  protected readonly criteria = computed(() => {
    const f = this.formation();
    return [
      { label: 'Niveau requis', value: this.readable(f.niveau_requis, 'Aucun prérequis') },
      { label: 'Nationalité', value: this.readable(f.nationalite_requise, 'Toutes') },
      {
        label: 'Baccalauréat',
        value: f.bac_requis?.trim().toLowerCase().startsWith('san')
          ? 'Bac non exigé'
          : this.readable(f.bac_requis, 'Toutes sections'),
      },
    ];
  });

  private readable(value: string, whenAll: string): string {
    const v = (value || '').trim();
    return !v || v.toLowerCase() === 'all' ? whenAll : v;
  }
}
