import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router';
import { App } from './App';
import { UiKitPage } from './ui/UiKitPage';
import { LocaleProvider } from './ui/locale';
import './styles.css';
import './design.css';
import './ui/tokens.css';
import './ui/components.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LocaleProvider><BrowserRouter><Routes><Route path="/ui-kit" element={<UiKitPage />} /><Route path="*" element={<App />} /></Routes></BrowserRouter></LocaleProvider>
  </StrictMode>,
);
