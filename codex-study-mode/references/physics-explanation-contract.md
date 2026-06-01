# Physics Explanation Contract

Use this contract whenever teaching physics, astronomy, cosmology, mathematical physics, or a paper containing physical concepts and equations.

The goal is to prevent two common failures:

- Copying a paper's complicated final result without explaining the bridge.
- Using abstract physical labels without saying what concrete quantity, state, field, transformation, or observable is involved.

## Abstract Concept Expansion

Do not use abstract terms as placeholders for understanding. When a term below appears, expand it into concrete objects.

Use this checklist:

1. Object: what is being discussed? A field, state, particle, equation, action, metric, perturbation, observable, coordinate description, or dataset?
2. Operation or transformation: what is done to it? Rotation, translation, parity, time reversal, gauge transformation, Lorentz transformation, projection, basis change, perturbation expansion, or decomposition?
3. Invariant or changed quantity: what stays the same or changes? Action, equation form, norm, probability, spectrum, correlation function, tensor component, polarization basis, measured signal, or likelihood?
4. Physical consequence: what follows? Conservation law, selection rule, degeneracy, polarization classification, allowed coupling, forbidden term, observable pattern, or scaling relation?
5. Minimal example: give the simplest example before returning to the paper or advanced formula.

## Required Expansions For Common Terms

When saying "symmetry", specify:

- The object: action, equations of motion, Hamiltonian, metric, field configuration, probability distribution, or observation.
- The transformation: for example `x -> x + a`, `x -> R x`, `phi(x) -> phi(x) + constant`, parity, or a gauge transformation.
- The invariant: action unchanged, equation form unchanged, observable unchanged, or probability distribution unchanged.
- The consequence: Noether charge, conserved quantity, degeneracy, mode classification, selection rule, or constraint on allowed terms.

When saying "chirality" or "helicity", specify:

- Chirality: the `gamma5` projection of a spinor, usually left-chiral and right-chiral components.
- Helicity: spin projected along momentum, usually left-helicity and right-helicity states.
- Whether the particle is massless or massive, because chirality and helicity coincide cleanly only in the massless limit.
- Which interaction or observable distinguishes the two.

When saying "gauge", specify:

- The redundant description or field variable.
- The gauge transformation.
- The gauge-invariant quantity or observable.
- Whether the current statement is about freedom of description, a constraint equation, or a physical degree of freedom.

When saying "mode", "polarization", or "perturbation", specify:

- What object is decomposed.
- The basis or classification used.
- The physical observable or signal each component contributes to.
- Which components are physical and which may be coordinate or gauge artifacts.

## Complex Result Bridge

Do not present a paper's final formula as the explanation. For any complex equation, fit, numerical result, or literature claim, provide a bridge:

1. Target quantity: what is being computed or constrained?
2. Inputs and assumptions: what background model, approximation, gauge, coordinate system, regime, or data selection is being used?
3. Skeleton derivation: the key two to four steps that connect inputs to result.
4. Approximation map: what is neglected, linearized, averaged, marginalized, or fit?
5. Interpretation: what changes physically if the result is larger, smaller, positive, negative, zero, or scale-dependent?
6. Skipped details: name what is being skipped and whether skipping it affects conceptual understanding.

Use phrases like "the paper obtains" only after the bridge is present.

## Examples

Bad:

> This follows from symmetry.

Good:

> Here the object is the action `S[phi]`. The transformation is a spatial translation `x -> x + a`, with the field rewritten as `phi'(x) = phi(x - a)`. The invariant is `S[phi'] = S[phi]`. The physical consequence is momentum conservation by Noether's theorem.

Bad:

> Tensor perturbations generate B modes.

Good:

> The object is the CMB polarization field on the sky, decomposed into E and B components. A tensor perturbation is a transverse-traceless metric perturbation `h_ij`; it changes photon geodesics and Thomson-scattering quadrupoles in a way with handed angular structure. The observable consequence is a curl-like B-mode polarization pattern, unlike scalar density perturbations at linear order.

Bad:

> Chirality determines the coupling.

Good:

> Here chirality means the left/right projection of a spinor using `P_L = (1 - gamma5)/2` and `P_R = (1 + gamma5)/2`. The two components are not simply "spin up/down"; they are components selected by `gamma5`. The physical consequence is that a weak-interaction term may couple only to the left-chiral component.
