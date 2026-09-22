import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './app/App';
import './styles/global.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('未找到根节点 root');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
