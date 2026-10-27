// Conversions WebAuthn entre le JSON du serveur (base64url) et les objets du navigateur.
// Utilise les fonctions natives quand Safari les fournit, sinon les conversions manuelles.

const toBytes = (b64url) => {
  const b64 = b64url.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(b64url.length / 4) * 4, "=");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0)).buffer;
};

const toB64url = (buffer) => {
  const bytes = new Uint8Array(buffer);
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

const withIds = (list) => (list || []).map((c) => ({ ...c, id: toBytes(c.id) }));

export function creationOptions(json) {
  if (PublicKeyCredential.parseCreationOptionsFromJSON) {
    return PublicKeyCredential.parseCreationOptionsFromJSON(json);
  }
  return {
    ...json,
    challenge: toBytes(json.challenge),
    user: { ...json.user, id: toBytes(json.user.id) },
    excludeCredentials: withIds(json.excludeCredentials),
  };
}

export function requestOptions(json) {
  if (PublicKeyCredential.parseRequestOptionsFromJSON) {
    return PublicKeyCredential.parseRequestOptionsFromJSON(json);
  }
  return { ...json, challenge: toBytes(json.challenge), allowCredentials: withIds(json.allowCredentials) };
}

export function credentialJSON(cred) {
  if (typeof cred.toJSON === "function") return cred.toJSON();
  const r = cred.response;
  const response = { clientDataJSON: toB64url(r.clientDataJSON) };
  if (r.attestationObject) {
    response.attestationObject = toB64url(r.attestationObject);
    response.transports = typeof r.getTransports === "function" ? r.getTransports() : [];
  } else {
    response.authenticatorData = toB64url(r.authenticatorData);
    response.signature = toB64url(r.signature);
    response.userHandle = r.userHandle ? toB64url(r.userHandle) : null;
  }
  return {
    id: cred.id,
    rawId: toB64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment || undefined,
    response,
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}
