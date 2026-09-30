import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// vitest runs without `globals: true`, so RTL never registers its automatic
// afterEach cleanup — without this, query() matches elements from a previous
// test in the same file.
afterEach(cleanup);
