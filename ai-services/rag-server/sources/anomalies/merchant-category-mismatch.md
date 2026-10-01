# Merchant category mismatch

Reference guidance for spotting transactions where the merchant, its category,
and the described purchase do not line up. A mismatch can reveal a disguised or
miscoded charge.

## Category versus amount
An amount that is implausible for the merchant's category — for example a
grocery store billing an electronics-sized sum — is a classic mismatch. The
larger the gap from typical spend in that category, the stronger the signal.

## Generic or shell-like merchants
Vague descriptors such as "Services", "Payments", or random strings hide the
true nature of a charge. Combined with an unusual amount, an uninformative
merchant name is worth flagging.

## Miscoded recurring charges
A known recurring payee suddenly appearing under a different category or name can
indicate a billing change or a disguised charge. Compare against the payee's
established descriptor.

## High-risk category creep
A charge that shifts an otherwise ordinary account into gambling, cash-advance,
crypto, or money-transfer categories is a mild signal, stronger when the amount
or merchant is also unfamiliar.

## Guidance
When citing a mismatch, name the conflict between the merchant, its category, and
the amount or description, rather than relying on the category label alone.
