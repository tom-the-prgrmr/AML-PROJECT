import { createContext, useContext } from "react";

export interface CaseHighlight {
  highlightIds: string[];
  setHighlight(ids: string[]): void;
  clearHighlight(): void;
}

/** Ids are node ids of the case graph (account_id or golden_customer_id). */
export const CaseHighlightContext = createContext<CaseHighlight>({
  highlightIds: [],
  setHighlight: () => {},
  clearHighlight: () => {},
});

export function useCaseHighlight(): CaseHighlight {
  return useContext(CaseHighlightContext);
}
