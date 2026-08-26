import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// vitest runs without `globals: true`, so React Testing Library never
// registers its automatic afterEach cleanup. Without this, multiple render()
// calls in one file stack up in the same document and queries silently match
// elements from a previous test.
afterEach(cleanup);
