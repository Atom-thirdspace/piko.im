function b64urlToBuf(value) {
  const pad = '='.repeat((4 - (value.length % 4)) % 4);
  const raw = atob((value + pad).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) { out[i] = raw.charCodeAt(i); }
  return out.buffer;
}

function bufToB64url(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i++) { s += String.fromCharCode(bytes[i]); }
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function csrf() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await res.json().catch(function () { return {}; });
  if (!res.ok) { throw new Error(data.error || 'Something went wrong.'); }
  return data;
}

window.webauthnSupported = function () {
  return !!(window.PublicKeyCredential && navigator.credentials);
};

window.webauthnRegister = async function (beginUrl, finishUrl, extra) {
  const options = await postJSON(beginUrl, extra || {});
  options.challenge = b64urlToBuf(options.challenge);
  options.user.id = b64urlToBuf(options.user.id);
  (options.excludeCredentials || []).forEach(function (c) {
    c.id = b64urlToBuf(c.id);
  });

  const cred = await navigator.credentials.create({ publicKey: options });
  return postJSON(finishUrl, Object.assign({
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    transports: (cred.response.getTransports && cred.response.getTransports()) || [],
    response: {
      clientDataJSON: bufToB64url(cred.response.clientDataJSON),
      attestationObject: bufToB64url(cred.response.attestationObject)
    }
  }, extra || {}));
};

window.webauthnAuthenticate = async function (beginUrl, finishUrl, extra) {
  const options = await postJSON(beginUrl, extra || {});
  options.challenge = b64urlToBuf(options.challenge);
  (options.allowCredentials || []).forEach(function (c) {
    c.id = b64urlToBuf(c.id);
  });

  const cred = await navigator.credentials.get({ publicKey: options });
  return postJSON(finishUrl, {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: bufToB64url(cred.response.clientDataJSON),
      authenticatorData: bufToB64url(cred.response.authenticatorData),
      signature: bufToB64url(cred.response.signature),
      userHandle: cred.response.userHandle
        ? bufToB64url(cred.response.userHandle) : null
    }
  });
};
