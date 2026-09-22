import { RouterProvider } from 'react-router-dom';
import { router } from './router';
import { DateProvider } from './DateContext';

export function App() {
  return (
    <DateProvider>
      <RouterProvider router={router} />
    </DateProvider>
  );
}
