"use client";
import { useRef, useState } from 'react';
import { Camera } from 'lucide-react';
import { Button } from '../ui/Button';
import { useCloudStore } from '../../lib/cloud-store';
import { trackActivity } from '../../lib/api-activity';
import { cloudApi, authMessage } from '../../lib/cloud-auth';

async function preparePhoto(file: File): Promise<string> {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Elegí una foto JPG, PNG o WebP.');
  if (file.size > 5 * 1024 * 1024) throw new Error('La foto debe pesar como máximo 5 MB.');
  const bitmap = await createImageBitmap(file);
  try {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d');
    if (!context) throw new Error('No se pudo preparar la foto.');
    const size = Math.min(bitmap.width, bitmap.height);
    context.fillStyle = '#ffffff'; context.fillRect(0, 0, 256, 256);
    context.drawImage(bitmap, (bitmap.width - size) / 2, (bitmap.height - size) / 2, size, size, 0, 0, 256, 256);
    return canvas.toDataURL('image/jpeg', 0.85).split(',')[1];
  } finally { bitmap.close(); }
}

export function ProfilePhotoEditor() {
  const { user, refresh } = useCloudStore();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  async function save(file?: File) {
    setError('');
    try {
      await trackActivity(async () => {
        const image = file ? await preparePhoto(file) : undefined;
        await cloudApi('/v1/me/avatar', file ? 'PATCH' : 'DELETE', file ? { image } : undefined, false, false);
        await refresh();
      }, file ? 'Foto de perfil actualizada.' : 'Foto de perfil eliminada.');
    } catch (e) { setError(authMessage(e)); }
    finally { if (input.current) input.current.value = ''; }
  }
  return <div className="profile-photo-editor">
    <input ref={input} type="file" className="sr-only" aria-label="Archivo de foto de perfil" accept="image/jpeg,image/png,image/webp" onChange={event => { const file = event.target.files?.[0]; if (file) void save(file); }} />
    <div className="profile-photo-actions"><Button variant="quiet" size="sm" onClick={() => input.current?.click()}><Camera size={16} />{user.avatarUrl ? 'Cambiar foto' : 'Agregar foto'}</Button>
      {user.avatarUrl && <Button variant="ghost" size="sm" onClick={() => void save()}>Quitar foto</Button>}</div>
    <p className="portal-muted">JPG, PNG o WebP, hasta 5 MB. La foto se recorta al centro.</p>
    {error && <p className="form-error" role="alert">{error}</p>}
  </div>;
}
