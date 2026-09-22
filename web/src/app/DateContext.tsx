import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { ApiError, getCandidateDates } from '../api/client';

export type DateContextValue = {
  dates: string[];
  asOf: string | null;
  setAsOf: (date: string) => void;
  loading: boolean;
  error: string | null;
  refreshDates: () => Promise<void>;
};

const defaultDateContext: DateContextValue = {
  dates: [],
  asOf: null,
  setAsOf: () => {},
  loading: false,
  error: null,
  refreshDates: async () => {},
};

export const DateContext = createContext<DateContextValue>(defaultDateContext);

export interface DateProviderProps {
  children: ReactNode;
  initialDates?: string[];
  initialAsOf?: string | null;
}

/**
 * 全局共享的候选快照日期上下文 Provider。
 * 在组件加载时自动拉取候选日期，默认选中最新日期。
 */
export function DateProvider({ children, initialDates, initialAsOf }: DateProviderProps) {
  const [dates, setDates] = useState<string[]>(initialDates ?? []);
  const [asOf, setAsOfState] = useState<string | null>(initialAsOf ?? null);
  const [loading, setLoading] = useState<boolean>(initialDates === undefined);
  const [error, setError] = useState<string | null>(null);

  const refreshDates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getCandidateDates();
      const fetchedDates = response.dates ?? [];
      setDates(fetchedDates);

      if (fetchedDates.length === 0) {
        setAsOfState(null);
      } else {
        const resolvedLatest =
          response.latest ?? fetchedDates[fetchedDates.length - 1] ?? null;
        setAsOfState(resolvedLatest);
      }
    } catch (err) {
      if (err instanceof ApiError || err instanceof Error) {
        setError(err.message);
      } else {
        setError('加载候选快照日期失败');
      }
      setAsOfState(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const setAsOf = useCallback((date: string) => {
    setAsOfState(date);
  }, []);

  useEffect(() => {
    if (initialDates === undefined) {
      void refreshDates();
    }
  }, [refreshDates, initialDates]);

  return (
    <DateContext.Provider
      value={{
        dates,
        asOf,
        setAsOf,
        loading,
        error,
        refreshDates,
      }}
    >
      {children}
    </DateContext.Provider>
  );
}

export function useDateContext(): DateContextValue {
  return useContext(DateContext);
}

export const useDate = useDateContext;
