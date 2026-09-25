// Shared between the upload UI (NewScreeningTab) and the submission payload
// (submitScreening) so both agree on exactly one set of document keys.
export const DOCUMENT_SLOTS = [
  { key: 'passport', label: 'Passport', hint: 'Bio-data page', required: true },
  { key: 'voterId', label: 'Voter ID (EPIC)', hint: 'Front side, EPIC number readable', required: false },
  { key: 'citizenship', label: 'Nepal Citizenship', hint: 'नागरिकता प्रमाणपत्र — front side', required: false },
  { key: 'nationalId', label: 'Aadhaar / National ID', hint: 'Side with the QR code — QR sharp and at least ~1/3 of the photo', required: true },
  { key: 'visa', label: 'Visa', hint: 'Visa page / sticker', required: true },
  { key: 'drivingLicence', label: 'Driving Licence', hint: 'Optional', required: false },
  { key: 'permit', label: 'Permit', hint: 'Optional', required: false },
] as const

export type DocKey = (typeof DOCUMENT_SLOTS)[number]['key'] | 'selfie'

export const REQUIRED_KEYS: DocKey[] = [...DOCUMENT_SLOTS.filter((s) => s.required).map((s) => s.key), 'selfie']

export const ALL_KEYS: DocKey[] = [...DOCUMENT_SLOTS.map((s) => s.key), 'selfie']
