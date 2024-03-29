# Copyright (c) 2022 - 2024, Oracle and/or its affiliates. All rights reserved.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/.

"""This module contains the CheckResult class for storing the result of a check."""
from dataclasses import dataclass
from enum import Enum
from typing import TypedDict

from macaron.database.table_definitions import CheckFacts
from macaron.slsa_analyzer.slsa_req import BUILD_REQ_DESC, ReqName


class CheckResultType(str, Enum):
    """This class contains the types of a check result."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    # A check is skipped from another check's result.
    SKIPPED = "SKIPPED"
    # A check is disabled from the user configuration.
    DISABLED = "DISABLED"
    # The result of the check is unknown or Macaron cannot resolve the
    # implementation of this check.
    UNKNOWN = "UNKNOWN"


@dataclass
class Evidence:
    """The class representing an evidence generated by a check."""

    #: The name of the evidence.
    name: str

    #: Determines whether the was evidence is found.
    found: bool

    #: The weight of the evidence.
    weight: float


class EvidenceWeightMap:
    """This class creates a map object for collected evidence."""

    def __init__(self, evidence_list: list[Evidence]) -> None:
        """Initialize the class.

        Parameters
        ----------
        evidence_list: list[Evidence]
            The list of evidences.
        """
        self.map_obj: dict[str, Evidence] = {}
        for evidence in evidence_list:
            self.add(evidence)

    def add(self, evidence: Evidence) -> None:
        """Add an evidence to the map.

        Parameters
        ----------
        evidence: Evidence
            The evidence object.
        """
        self.map_obj[evidence.name] = evidence

    def update_result(self, name: str, found: bool) -> None:
        """Update the result if an evidence is found.

        Parameters
        ----------
        found: bool
            True if evidence was found.
        """
        if evidence := self.map_obj.get(name):
            evidence.found = found

    def get_max_score(self) -> float:
        """Get the maximum possible score in this map.

        Returns
        -------
        float
            The maximum possible score or zero if the map is empty.
        """
        if self.map_obj.values():
            return sum(e.weight for e in self.map_obj.values())
        return 0

    def get_score(self) -> float:
        """Compute the score using the evidence result and weights.

        Returns
        -------
        float
            The aggregate score or zero if the map is empty.
        """
        if self.map_obj.values():
            return sum(e.weight * int(e.found) for e in self.map_obj.values())
        return 0


class Confidence(float, Enum):
    """This class contains confidence score for a check result.

    The scores must be in the range [0.0, 1.0].
    """

    #: A high confidence score.
    HIGH = 1.0

    #: A medium confidence score.
    MEDIUM = 0.7

    #: A low confidence score.
    LOW = 0.4

    @classmethod
    def normalize(cls, evidence_weight_map: EvidenceWeightMap) -> "Confidence":
        """Normalize the score based on the provided evidence weight map.

        The values in the evidence weight map are expected to be positive. Expect invalid results if negative weights
        are passed to this function.

        Parameters
        ----------
        evidence_weight_map: EvidenceWeightMap
            The map that contains the detected evidence and their corresponding weight.

        """
        max_score = evidence_weight_map.get_max_score()
        # If the maximum score is zero, there is no need to normalize and just return the highest confidence level.
        if max_score == 0:
            return cls.HIGH

        score = evidence_weight_map.get_score()

        # If the difference is zero, there is no need to normalize.
        if cls.HIGH - cls.LOW == 0:
            return cls.HIGH

        normalized_score = score / max_score

        # Return the confidence level that is closest to the normalized score.
        return min(cls, key=lambda c: abs(c.value - normalized_score))


class JustificationType(str, Enum):
    """This class contains the type of a justification that will be used in creating the HTML report."""

    #: If a justification has a text type, it will be added as a plain text.
    TEXT = "text"

    #: If a justification has a href type, it will be added as a hyperlink.
    HREF = "href"


@dataclass(frozen=True)
class CheckInfo:
    """This class identifies and describes a check."""

    #: The id of the check.
    check_id: str

    #: The description of the check.
    check_description: str

    #: The list of SLSA requirements that this check addresses.
    eval_reqs: list[ReqName]


@dataclass(frozen=True)
class CheckResultData:
    """This class stores the result of a check."""

    #: List of result tables produced by the check.
    result_tables: list[CheckFacts]

    #: Result type of the check (e.g. PASSED).
    result_type: CheckResultType

    @property
    def justification_report(self) -> list[tuple[Confidence, list]]:
        """
        Return a sorted list of justifications based on confidence scores in descending order.

        These justifications are generated from the tables in the database.
        Note that the elements in the justification will be rendered differently based on their types:

        * a :class:`JustificationType.TEXT` element is displayed in plain text in the HTML report.
        * a :class:`JustificationType.HREF` element is rendered as a hyperlink in the HTML report.

        Returns
        -------
        list[tuple[Confidence, list]]
        """
        justification_list: list = []
        for result in self.result_tables:
            # The HTML report generator requires the justification elements that need to be rendered in HTML
            # to be passed as a dictionary as key-value pairs. The elements that need to be displayed in plain
            # text should be passed as string values.
            dict_elements: dict[str, str] = {}
            list_elements: list[str | dict] = []

            # Look for columns that are have "justification" metadata.
            for col in result.__table__.columns:
                column_value = getattr(result, col.name)
                if col.info.get("justification") and column_value:
                    if col.info.get("justification") == JustificationType.HREF:
                        dict_elements[col.name] = column_value
                    elif col.info.get("justification") == JustificationType.TEXT:
                        list_elements.append(f"{col.name}: {column_value}")

            # Add the dictionary elements to the list of justification elements.
            if dict_elements:
                list_elements.append(dict_elements)

            if list_elements:
                justification_list.append((result.confidence, list_elements))

        # If there are no justifications available, return a default "Not Available" one.
        if not justification_list:
            return [(Confidence.HIGH, ["Not Available."])]

        # Sort the justification list based on the confidence score in descending order.
        return sorted(justification_list, key=lambda item: item[0], reverse=True)


@dataclass(frozen=True)
class CheckResult:
    """This class stores the result of a check, including the description of the check that produced it."""

    #: Info about the check that produced these results.
    check: CheckInfo

    #: The results produced by the check.
    result: CheckResultData

    def get_summary(self) -> dict:
        """Get a flattened dictionary representation for this CheckResult, in a format suitable for the output report.

        The SLSA requirements, in particular, are translated into a list of their textual descriptions, to be suitable
        for display to users in the output report (as opposed to the internal representation as a list of enum identifiers).

        Returns
        -------
        dict
        """
        return {
            "check_id": self.check.check_id,
            "check_description": self.check.check_description,
            "slsa_requirements": [str(BUILD_REQ_DESC.get(req)) for req in self.check.eval_reqs],
            # The justification report is sorted and the first element has the highest confidence score.
            "justification": self.result.justification_report[0][1],
            "result_tables": self.result.result_tables,
            "result_type": self.result.result_type,
        }


class SkippedInfo(TypedDict):
    """This class stores the information about a skipped check."""

    check_id: str
    suppress_comment: str


def get_result_as_bool(check_result_type: CheckResultType) -> bool:
    """Return the CheckResultType as bool.

    This method returns True only if the result type is PASSED else it returns False.

    Parameters
    ----------
    check_result_type : CheckResultType
        The check result type to return the bool value.

    Returns
    -------
    bool
    """
    if check_result_type in (CheckResultType.FAILED, CheckResultType.UNKNOWN):
        return False

    return True
