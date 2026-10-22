import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    title: 'Assistant Admissions',
    loadComponent: () => import('./chat/chat.component').then((m) => m.ChatComponent),
  },
  { path: '**', redirectTo: '' },
];
