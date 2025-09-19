import React, { useCallback, useEffect, useMemo, useState } from 'react';

const STORAGE_KEYS = {
  token: 'session_token',
};

const CATEGORY_LABELS = {
  github: 'GitHub',
  openai: 'OpenAI',
  general: 'General',
};

const buildFormState = (rawSettings) => {
  if (!Array.isArray(rawSettings)) {
    return [];
  }
  return rawSettings.map((item) => {
    const key = item && typeof item.key === 'string' ? item.key : '';
    const label = item && typeof item.label === 'string' ? item.label : key;
    const category = item && typeof item.category === 'string' ? item.category : 'general';
    const helpText = item && typeof item.help_text === 'string' ? item.help_text : '';
    const placeholder = item && typeof item.placeholder === 'string' ? item.placeholder : '';
    const isSecret = Boolean(item && item.is_secret);
    const configured = Boolean(item && item.configured);
    const value = item && typeof item.value === 'string' ? item.value : '';
    const defaultValue = item && typeof item.default === 'string' ? item.default : '';
    return {
      key,
      label,
      category,
      helpText,
      placeholder,
      isSecret,
      configured,
      defaultValue,
      originalValue: isSecret ? (configured ? '__SECRET__' : '') : value,
      draftValue: isSecret ? '' : value,
      dirty: false,
      shouldClear: false,
    };
  });
};

const groupByCategory = (settings) => {
  const groups = new Map();
  settings.forEach((setting) => {
    const category = setting.category || 'general';
    if (!groups.has(category)) {
      groups.set(category, []);
    }
    groups.get(category).push(setting);
  });
  return Array.from(groups.entries());
};

const AdminIntegrations = () => {
  const [formState, setFormState] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const groupedSettings = useMemo(() => groupByCategory(formState), [formState]);

  const getToken = () => {
    if (typeof window === 'undefined' || !window.localStorage) {
      return '';
    }
    return window.localStorage.getItem(STORAGE_KEYS.token) || '';
  };

  const fetchSettings = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setError('No se encontró un token de sesión válido. Inicia sesión nuevamente.');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError('');
    setSuccess('');
    try {
      const response = await fetch('/api/admin/integrations', {
        headers: {
          Authorization: `Bearer ${token}`,
        },
        credentials: 'include',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message =
          typeof payload.error === 'string' && payload.error.trim()
            ? payload.error.trim()
            : 'No se pudieron cargar las integraciones.';
        setError(message);
        setFormState([]);
        setLoading(false);
        return;
      }
      setFormState(buildFormState(payload.settings));
    } catch (err) {
      setError('Error de conexión al cargar las integraciones.');
      setFormState([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  const handleInputChange = useCallback((key, value) => {
    setFormState((prev) =>
      prev.map((setting) => {
        if (setting.key !== key) {
          return setting;
        }
        const draftValue = value;
        if (setting.isSecret) {
          const dirty = Boolean(draftValue);
          return {
            ...setting,
            draftValue,
            dirty,
            shouldClear: false,
          };
        }
        const dirty = draftValue !== setting.originalValue;
        return {
          ...setting,
          draftValue,
          dirty,
        };
      }),
    );
  }, []);

  const handleClearSecret = useCallback((key) => {
    setFormState((prev) =>
      prev.map((setting) => {
        if (setting.key !== key) {
          return setting;
        }
        if (!setting.isSecret) {
          return setting;
        }
        return {
          ...setting,
          draftValue: '',
          dirty: false,
          shouldClear: true,
        };
      }),
    );
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError('');
    setSuccess('');
    const token = getToken();
    if (!token) {
      setError('La sesión expiró. Inicia sesión nuevamente.');
      return;
    }
    const updates = formState
      .filter((setting) => setting.shouldClear || setting.dirty)
      .map((setting) => {
        if (setting.shouldClear) {
          return { key: setting.key, clear: true };
        }
        return { key: setting.key, value: setting.draftValue };
      });
    if (updates.length === 0) {
      setSuccess('No hay cambios para guardar.');
      return;
    }
    setSaving(true);
    try {
      const response = await fetch('/api/admin/integrations', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        credentials: 'include',
        body: JSON.stringify({ updates }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message =
          typeof payload.error === 'string' && payload.error.trim()
            ? payload.error.trim()
            : 'No se pudieron guardar los cambios.';
        setError(message);
        return;
      }
      setFormState(buildFormState(payload.settings));
      setSuccess('Integraciones actualizadas correctamente.');
    } catch (err) {
      setError('Error de conexión al guardar los cambios.');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    fetchSettings();
  };

  return (
    <main className="admin-integrations">
      <header className="admin-integrations__header">
        <h1>Integraciones</h1>
        <p>
          Administra las credenciales de GitHub y OpenAI utilizadas por el verificador automático. Los cambios son inmediatos y
          afectan a todas las verificaciones nuevas.
        </p>
      </header>
      {error && <div className="admin-integrations__alert admin-integrations__alert--error">{error}</div>}
      {success && <div className="admin-integrations__alert admin-integrations__alert--success">{success}</div>}
      {loading ? (
        <p>Cargando configuraciones…</p>
      ) : (
        <form className="admin-integrations__form" onSubmit={handleSubmit}>
          {groupedSettings.length === 0 ? (
            <p>No hay campos de configuración disponibles.</p>
          ) : (
            groupedSettings.map(([category, items]) => (
              <section key={category} className="admin-integrations__section">
                <h2>{CATEGORY_LABELS[category] || category}</h2>
                {items.map((setting) => (
                  <div key={setting.key} className="admin-integrations__field">
                    <label className="admin-integrations__label" htmlFor={`setting-${setting.key}`}>
                      {setting.label}
                    </label>
                    <input
                      id={`setting-${setting.key}`}
                      type={setting.isSecret ? 'password' : 'text'}
                      value={setting.draftValue}
                      onChange={(event) => handleInputChange(setting.key, event.target.value)}
                      placeholder={setting.placeholder || setting.defaultValue || ''}
                      autoComplete="off"
                      className="admin-integrations__input"
                      disabled={saving}
                    />
                    {setting.isSecret && setting.configured && !setting.shouldClear && !setting.dirty && (
                      <p className="admin-integrations__hint">Valor guardado. Deja el campo vacío para conservarlo.</p>
                    )}
                    {setting.isSecret && (
                      <div className="admin-integrations__secret-actions">
                        <button
                          type="button"
                          className="admin-integrations__clear"
                          onClick={() => handleClearSecret(setting.key)}
                          disabled={saving || !setting.configured}
                        >
                          Quitar valor guardado
                        </button>
                        {setting.shouldClear && <span className="admin-integrations__hint">Se eliminará al guardar.</span>}
                      </div>
                    )}
                    {setting.helpText && (
                      <p className="admin-integrations__help">{setting.helpText}</p>
                    )}
                    {!setting.isSecret && !setting.draftValue && setting.defaultValue && (
                      <p className="admin-integrations__hint">
                        Valor sugerido: <code>{setting.defaultValue}</code>
                      </p>
                    )}
                  </div>
                ))}
              </section>
            ))
          )}
          <div className="admin-integrations__actions">
            <button type="button" onClick={handleReset} disabled={loading || saving}>
              Descartar cambios
            </button>
            <button type="submit" disabled={saving}>
              {saving ? 'Guardando…' : 'Guardar cambios'}
            </button>
          </div>
        </form>
      )}
    </main>
  );
};

export default AdminIntegrations;
