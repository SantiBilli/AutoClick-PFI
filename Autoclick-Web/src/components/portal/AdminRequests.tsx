"use client";
import { useState } from "react";
import { Button } from "../ui/Button";
import { Avatar } from "../ui/Avatar";
import { useCloudStore } from '../../lib/cloud-store';
import { Panel } from '../ui/Panel';
import { Select } from '../ui/Select';

export function AdminRequests() {
  const { businessRequests, updateBusinessRequest, users, user, updateUser } = useCloudStore();
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const matches = users.filter(u => `${u.name} ${u.email}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const pages = Math.max(1, Math.ceil(matches.length / 15));
  const currentPage = Math.min(page, pages);
  const rows = matches.slice((currentPage - 1) * 15, currentPage * 15);
  return <>
    <Panel className="portal-card">
      <div className="portal-card__heading"><h2>Solicitudes empresariales</h2></div>
      {!businessRequests.length ? <p className="portal-muted">Todavía no hay solicitudes.</p> : <div className="table-wrap"><table className="portal-table">
        <thead><tr><th>Empresa</th><th>Contacto</th><th>Necesidad</th><th>Estado</th></tr></thead>
        <tbody>{businessRequests.map(r => <tr key={r.id}><td>{r.companyName}<small> · {r.estimatedUsers} usuarios</small></td><td>{r.contactName}<br />{r.contactEmail}</td><td>{r.useCase}{r.notes && <p>{r.notes}</p>}</td><td>
          <Select aria-label={`Estado de ${r.companyName}`} value={r.status} onChange={e => { void updateBusinessRequest(r.id, e.target.value).catch(() => {}); }}>
            <option value="pending">Pendiente</option><option value="reviewing">En revisión</option><option value="approved">Aprobada</option><option value="rejected">Rechazada</option>
          </Select>
        </td></tr>)}</tbody>
      </table></div>}
      <p className="portal-muted">Aprobar una solicitud no crea una organización ni envía un correo. Creá la organización y asigná al propietario desde Organizaciones.</p>
    </Panel>
    <Panel className="portal-card">
      <div className="portal-card__heading"><h2>Cuentas registradas</h2><span className="ui-badge">{matches.length} cuentas</span></div>
      <label className="form-field accounts-search">Buscar cuentas<input type="search" placeholder="Nombre o correo electrónico" value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} /></label>
      <div className="table-wrap"><table className="portal-table"><thead><tr><th>Persona</th><th>Email</th><th>Acceso</th></tr></thead><tbody>
        {rows.map(u => <tr key={u.id}><td><span className="table-primary"><Avatar user={u} className="avatar" /><strong>{u.name}</strong></span></td><td>{u.email}</td><td><Select aria-label={`Acceso de ${u.name}`} disabled={u.id === user.id} value={u.status} onChange={e => { void updateUser(u.id, e.target.value).catch(() => {}); }}><option value="active">Activo</option><option value="inactive">Suspendido</option></Select></td></tr>)}
        {!rows.length && <tr><td colSpan={3}>No se encontraron cuentas.</td></tr>}
      </tbody></table></div>
      <nav className="accounts-pagination" aria-label="Paginación de cuentas"><span>Página {currentPage} de {pages}</span><Button variant="quiet" size="sm" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Anterior</Button><Button variant="quiet" size="sm" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>Siguiente</Button></nav>
    </Panel>
  </>;
}
