import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ChatComponent } from './chat/chat.component';
import { FormationCardComponent } from './chat/components/formation-card/formation-card.component';
import { Formation } from './core/chat.models';
import { FormatTextPipe } from './shared/format-text.pipe';

describe('ChatComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChatComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('renders the sidebar, the header, the welcome message and the input', async () => {
    const fixture = TestBed.createComponent(ChatComponent);
    await fixture.whenStable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.brand-name')?.textContent).toContain('Assistant Admission');
    expect(el.querySelector('h1')?.textContent).toContain('Nouvelle discussion');
    expect(el.textContent).toContain('En ligne');
    expect(el.querySelectorAll('.chip').length).toBe(4);
    expect(el.querySelector('input[placeholder="Posez votre question..."]')).toBeTruthy();
  });
});

describe('FormationCardComponent', () => {
  const formation: Formation = {
    id: 1,
    diplome: 'Brevet de Technicien Professionnel',
    specialite: 'Informatique de Gestion',
    ecole: 'IMSET GABES',
    niveau_requis: '2ème avec succés ou CAP dans le même secteur',
    nationalite_requise: 'All',
    bac_requis: 'san bac',
  };

  it('shows readable criteria and emits on register', async () => {
    const fixture = TestBed.createComponent(FormationCardComponent);
    fixture.componentRef.setInput('formation', formation);
    let registered: Formation | undefined;
    fixture.componentInstance.register.subscribe((f) => (registered = f));
    await fixture.whenStable();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Toutes');
    expect(el.textContent).toContain('Bac non exigé');
    (el.querySelector('button.btn-primary') as HTMLButtonElement).click();
    expect(registered?.id).toBe(1);
  });
});

describe('FormatTextPipe', () => {
  const pipe = new FormatTextPipe();

  it('escapes HTML and renders bold and bullet lists', () => {
    const html = pipe.transform('**Pièces** :\n- CIN\n- <script>x</script>');
    expect(html).toContain('<strong>Pièces</strong>');
    expect(html).toContain('<li>CIN</li>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
  });
});
