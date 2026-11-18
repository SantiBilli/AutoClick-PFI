import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET() {
  // Dynamic lookup prevents Next.js from inlining NEXT_PUBLIC values at build time.
  // Only these public identifiers are returned; never serialize process.env.
  const read = (name: string) => process.env[name]?.trim() ?? '';
  const userPoolId = read('NEXT_PUBLIC_COGNITO_USER_POOL_ID');
  const userPoolClientId = read('NEXT_PUBLIC_COGNITO_CLIENT_ID');
  const apiUrl = read('NEXT_PUBLIC_AUTOCLICK_API_URL').replace(/\/+$/, '');
  const headers = { 'Cache-Control': 'no-store, max-age=0' };
  let validApi = false;
  try {
    const url = new URL(apiUrl);
    validApi = url.protocol === 'https:' && !url.username && !url.password && !url.search && !url.hash;
  } catch { /* A missing/invalid value is reported without exposing server configuration. */ }
  if (!/^[a-z0-9-]+_[A-Za-z0-9]+$/.test(userPoolId) || !/^[a-z0-9]+$/.test(userPoolClientId) || !validApi) {
    return NextResponse.json({ message: 'La autenticación todavía no está configurada. Revisá las variables de entorno del servicio.' }, { status: 503, headers });
  }
  return NextResponse.json({ userPoolId, userPoolClientId, apiUrl }, { headers });
}
