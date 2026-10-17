declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf8'): string;
  export function readdirSync(path: string): string[];
}

declare module 'node:path' {
  export function join(...paths: string[]): string;
  export function dirname(path: string): string;
}

declare module 'node:url' {
  export function fileURLToPath(url: string | URL): string;
}

declare const process: { cwd(): string };
