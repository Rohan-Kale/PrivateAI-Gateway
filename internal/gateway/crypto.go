package gateway

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"io"
)

type Vault struct {
	aead cipher.AEAD
	key  []byte
}

func NewVault(key []byte) (*Vault, error) {
	if len(key) != 32 {
		return nil, errors.New("VAULT_KEY must decode to 32 bytes")
	}
	b, e := aes.NewCipher(key)
	if e != nil {
		return nil, e
	}
	a, e := cipher.NewGCM(b)
	return &Vault{aead: a, key: key}, e
}
func (v *Vault) Seal(scope, plain string) (string, error) {
	nonce := make([]byte, v.aead.NonceSize())
	if _, e := io.ReadFull(rand.Reader, nonce); e != nil {
		return "", e
	}
	return base64.RawURLEncoding.EncodeToString(v.aead.Seal(nonce, nonce, []byte(plain), []byte(scope))), nil
}
func (v *Vault) Open(scope, sealed string) (string, error) {
	b, e := base64.RawURLEncoding.DecodeString(sealed)
	if e != nil || len(b) < v.aead.NonceSize() {
		return "", errors.New("invalid ciphertext")
	}
	n := v.aead.NonceSize()
	p, e := v.aead.Open(nil, b[:n], b[n:], []byte(scope))
	return string(p), e
}
func (v *Vault) Hash(s string) string {
	h := hmac.New(sha256.New, v.key)
	h.Write([]byte(s))
	return hex.EncodeToString(h.Sum(nil))
}
func newID() string {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}
	return hex.EncodeToString(b)
}
