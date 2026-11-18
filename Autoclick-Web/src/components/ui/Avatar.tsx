"use client";
import Image from 'next/image';
import { useState } from 'react';
type Person = { name: string; avatarInitials: string; avatarUrl?: string };
export function Avatar({ user, className = 'portal-avatar' }: { user?: Person; className?: string }) {
  const [failed, setFailed] = useState('');
  return <span className={`${className} user-avatar`}>
    {user?.avatarUrl && failed !== user.avatarUrl ? <Image src={user.avatarUrl} alt={`Foto de ${user.name}`} width={96} height={96} unoptimized onError={() => setFailed(user.avatarUrl ?? '')} /> : <span aria-hidden="true">{user?.avatarInitials ?? '?'}</span>}
  </span>;
}
