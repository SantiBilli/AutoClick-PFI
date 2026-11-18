"use client";
import { Modal } from "../ui/Modal";
export function ChangeRoleDialog({ open, onClose }: { open: boolean; onClose: () => void }) { return <Modal open={open} title="Roles por área" onClose={onClose}><p className="portal-muted">Los roles se asignan por cada membresía de área.</p></Modal>; }
