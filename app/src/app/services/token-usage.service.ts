import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, timer } from 'rxjs';
import { switchMap } from 'rxjs/operators';
import { environment } from '../../environments/environment';

export interface LineMeta {
  key: string;
  label: string;
  note: string | null;
}

export interface TokenSample {
  ts: string;
  since: string;
  values: { [key: string]: number };
}

export interface TokenUsageResponse {
  lines: LineMeta[];
  samples: TokenSample[];
}

/**
 * Reads the 2h-sampled Claude-CLI token usage per agent-line (T-287), written
 * by tools/sample_token_usage.py via the cortex-board-token-sample.timer
 * (01/03/05/07/.../23 local -- hits 05:00 before and 07:00 after the morning
 * routines on purpose, see token_usage.py).
 */
@Injectable({ providedIn: 'root' })
export class TokenUsageService {
  readonly base = environment.boardApi;

  constructor(private http: HttpClient) {}

  getUsage(): Observable<TokenUsageResponse> {
    return this.http.get<TokenUsageResponse>(`${this.base}/api/token-usage`);
  }

  /** Emit now and then every `ms` milliseconds (default 5min -- this is a 2h-sampled series, no need to poll fast). */
  pollUsage(ms = 300000): Observable<TokenUsageResponse> {
    return timer(0, ms).pipe(switchMap(() => this.getUsage()));
  }
}
