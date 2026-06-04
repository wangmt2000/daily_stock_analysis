import { validateStockCode } from './validation';
import { normalizeStockCode } from './stockCode';

const EXCHANGE_PREFIXES = new Set(['SH', 'SZ', 'BJ', 'HK', 'US', 'SS']);

export function extractStockCodeFromMessage(message: string): string | null {
  // More specific patterns first to avoid greedy \d{6} capturing inside .SH/.SZ codes
  const patterns = [
    /\b(30\d{4}\.SZ)\b/gi,
    /\b(68\d{4}\.SH)\b/gi,
    /\b(00\d{4}\.SZ)\b/gi,
    /\b(60\d{4}\.SH)\b/gi,
    /\b(SH\d{6})\b/gi,
    /\b(SZ\d{6})\b/gi,
    /\b(BJ\d{6})\b/gi,
    /\b(hk\d{4,5})\b/gi,
    /\b(\d{1,5}\.HK)\b/gi,
    /\b(\d{5,6})\b/g,
    /\b([A-Z]{2,5})\b/g,
  ];
  for (const pattern of patterns) {
    const matches = message.match(pattern);
    if (matches) {
      for (const m of matches) {
        if (EXCHANGE_PREFIXES.has(m.toUpperCase())) {
          continue;
        }
        const { valid, normalized } = validateStockCode(m);
        if (valid) return normalizeStockCode(normalized);
      }
    }
  }
  return null;
}
