import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { PwaUpdatePrompt } from './PwaUpdatePrompt';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <main>
      <h1>НарядAI</h1>
      <p>Система ремонтных нарядов</p>
      <p>Базовый интерфейс запущен. Рабочие экраны ещё в разработке.</p>
      <PwaUpdatePrompt />
    </main>
  </StrictMode>,
);
