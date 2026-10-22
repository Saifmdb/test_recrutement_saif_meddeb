export interface Formation {
  id: number;
  diplome: string;
  specialite: string;
  ecole: string;
  niveau_requis: string;
  nationalite_requise: string;
  bac_requis: string;
}

export interface Recap {
  prenom: string;
  nom: string;
  email: string;
  telephone: string;
  formation: Formation;
}

export interface Source {
  ref: number;
  document: string;
  extrait: string;
}

export interface ChatMessage {
  id?: number;
  role: 'user' | 'assistant';
  text: string;
  payload?: {
    cards?: Formation[];
    recap?: Recap | null;
    sources?: Source[];
    confirmation?: { reference: string; statut: string } | null;
  };
  error?: boolean;
}

export interface ChatResponse {
  conversation_id: string;
  message: ChatMessage;
}

export interface ConversationSummary {
  id: string;
  title: string;
}

export interface HistoryResponse {
  conversation_id: string;
  messages: ChatMessage[];
}
